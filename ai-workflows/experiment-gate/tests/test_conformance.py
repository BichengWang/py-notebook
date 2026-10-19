"""Conformance vectors: the verifier agrees with every manifest entry and every digest can be recomputed."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from expgate.jcs import canonicalize
from expgate.run import main as run_main

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "conformance"
MANIFEST = json.loads((CONFORMANCE / "manifest.json").read_text(encoding="utf-8"))
SCHEMA_IDS = "https://github.com/BichengWang/ai-decision-system/schema/expgate/decision.v{}.json"

def _load_schema_validation():
    """The dev-only validator helper; None when jsonschema is not installed."""
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        return None
    spec = importlib.util.spec_from_file_location("expgate_schema_validation", Path(__file__).with_name("schema_validation.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema_validation = _load_schema_validation()


def pointer(document, ref: str):
    """RFC 6901 JSON Pointer."""
    value = document
    if ref == "":
        return value
    for token in ref.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def canonical_bytes(kind: str, value) -> bytes:
    if kind == "rfc8785":
        return canonicalize(value)
    if kind == "python-json-v1":
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    raise AssertionError(kind)


class ManifestTest(unittest.TestCase):
    def test_manifest_header_and_coverage(self):
        self.assertEqual((MANIFEST["format"], MANIFEST["package"]), (1, "expgate"))
        expects = {(v["path"].split("/")[0], v["expect"]) for v in MANIFEST["vectors"]}
        self.assertEqual(expects, {("valid", "valid"), ("tampered", "tampered"), ("invalid", "invalid")})
        listed = {v["path"] for v in MANIFEST["vectors"]}
        listed |= {d["canonical_file"] for v in MANIFEST["vectors"] for d in v.get("digests", [])}
        on_disk = {p.relative_to(CONFORMANCE).as_posix() for sub in ("valid", "tampered", "invalid")
                   for p in (CONFORMANCE / sub).rglob("*") if p.is_file()}
        self.assertEqual(listed, on_disk)
        for version in (2, 3):
            for expect in ("valid", "tampered", "invalid"):
                with self.subTest(version=version, expect=expect):
                    self.assertTrue(any(v["path"].startswith(f"{expect}/decision-v{version}-")
                                        for v in MANIFEST["vectors"]))

    def test_exit_codes_follow_expectation_and_valid_vectors_carry_digests(self):
        for vector in MANIFEST["vectors"]:
            with self.subTest(vector=vector["path"]):
                self.assertEqual(vector["verify"]["exit_code"], {"valid": 0, "tampered": 1, "invalid": 2}[vector["expect"]])
                self.assertEqual(vector["verify"]["command"], ["experiment-gate-verify", "{path}"])
                self.assertEqual(bool(vector.get("digests")), vector["expect"] == "valid")
                self.assertTrue(vector["note"])

    def test_committed_tree_equals_a_fresh_generation(self):
        spec = importlib.util.spec_from_file_location("expgate_conformance_generate", CONFORMANCE / "generate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.differences(module.build(), module.existing()), [])

    def test_fresh_generation_comparison_catches_changes(self):
        spec = importlib.util.spec_from_file_location("expgate_conformance_generate_2", CONFORMANCE / "generate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fresh = module.build()
        name = "valid/decision-v3-ship.json"
        record = json.loads(fresh[name])
        # A last-digit difference in a derived float is the platform effect the comparison tolerates ...
        record["metrics"][0]["se"] *= 1 + 1e-12
        self.assertEqual(module.differences(fresh, {**fresh, name: json.dumps(record, indent=2).encode()}), [])
        # ... an edit to the input, a larger change or a missing file is not.
        record["metrics"][0]["se"] *= 1.001
        self.assertEqual(module.differences(fresh, {**fresh, name: json.dumps(record, indent=2).encode()}), [name])
        record = json.loads(fresh[name])
        record["input"]["seed"] = 1
        self.assertEqual(module.differences(fresh, {**fresh, name: json.dumps(record, indent=2).encode()}), [name])
        self.assertEqual(module.differences(fresh, {k: v for k, v in fresh.items() if k != name}), [name])


class VerifierOverVectorsTest(unittest.TestCase):
    def test_verifier_exit_code_matches_every_vector(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        for vector in MANIFEST["vectors"]:
            with self.subTest(vector=vector["path"]):
                command = [sys.executable, "-m", "expgate.verify"]
                command += [str(CONFORMANCE / vector["path"]) if part == "{path}" else part
                            for part in vector["verify"]["command"][1:]]
                done = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, vector["verify"]["exit_code"], done.stdout + done.stderr)

    def test_every_digest_entry_recomputes(self):
        checked = 0
        for vector in MANIFEST["vectors"]:
            for entry in vector.get("digests", []):
                with self.subTest(vector=vector["path"], digest=entry["value"]):
                    document = json.loads((CONFORMANCE / vector["path"]).read_text(encoding="utf-8"))
                    covered = pointer(document, entry["covers"])
                    for member in entry["exclude"]:
                        covered = {k: v for k, v in covered.items() if k != member}
                    canonical = (CONFORMANCE / entry["canonical_file"]).read_bytes()
                    self.assertEqual(canonical, canonical_bytes(entry["canonicalization"], covered))
                    self.assertFalse(canonical.endswith(b"\n"))
                    self.assertEqual(hashlib.sha256(canonical).hexdigest(), pointer(document, entry["value"]))
                    checked += 1
        self.assertEqual(checked, len([v for v in MANIFEST["vectors"] if v["expect"] == "valid"]))

    def test_jcs_edge_vectors_separate_the_two_canonicalizations(self):
        v3 = (CONFORMANCE / "valid" / "decision-v3-jcs-edge.input.canonical").read_text(encoding="utf-8")
        v2 = (CONFORMANCE / "valid" / "decision-v2-jcs-edge.input.canonical").read_text(encoding="utf-8")
        self.assertIn('"margin":5,', v3)
        self.assertIn('"margin":5.0,', v2)
        self.assertIn('"mean":1e-7,', v3)
        self.assertIn('"mean":1e-07,', v2)
        self.assertIn('"mean":40,', v3)
        self.assertIn('"mean":40.0,', v2)
        self.assertLess(v3.index("\U0001f600"), v3.index("\uff5e"))
        self.assertLess(v2.index("\uff5e"), v2.index("\U0001f600"))


@unittest.skipIf(schema_validation is None, "jsonschema is not installed (dev and CI only)")
class SchemaTest(unittest.TestCase):
    def test_schema_files_are_valid_and_identified(self):
        for version in (2, 3):
            with self.subTest(version=version):
                schema = schema_validation.load_schema(version)
                schema_validation.validator(version)
                self.assertEqual(schema["$id"], SCHEMA_IDS.format(version))
                self.assertEqual(schema["properties"]["schema_version"], {"const": version})
                self.assertIn("python-json-v1" if version == 2 else "RFC 8785", schema["$comment"])

    def test_schema_validity_matches_every_manifest_document(self):
        for vector in MANIFEST["vectors"]:
            for document in vector.get("documents", []):
                with self.subTest(vector=vector["path"]):
                    self.assertEqual(document["path"], ".")
                    version = 3 if document["schema"].endswith("decision.v3.json") else 2
                    self.assertEqual(document["schema"], f"expgate/schema/decision.v{version}.json")
                    text = (CONFORMANCE / vector["path"]).read_text(encoding="utf-8")
                    problems = schema_validation.errors(json.loads(text), version)
                    self.assertEqual(not problems, document["schema_valid"], problems)

    def test_records_written_by_the_cli_validate(self):
        examples = sorted((ROOT / "examples").glob("*.json"))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_main(["--all-scenarios", "--out", str(Path(tmp, "scenarios"))]), 0)
            self.assertEqual(run_main(["--input", *map(str, examples), "--out", str(Path(tmp, "examples"))]), 0)
            records = sorted(Path(tmp).glob("*/*/decision.json"))
            self.assertGreaterEqual(len(records), 7 + len(examples))
            for path in records:
                with self.subTest(record=path.parent.name):
                    document = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual(schema_validation.errors(document, document["schema_version"]), [])

    def test_schema_rejects_unknown_members_and_bad_values(self):
        record = json.loads((CONFORMANCE / "valid" / "decision-v3-ship.json").read_text(encoding="utf-8"))
        cases = {
            "unknown input key": lambda r: r["input"].update(polcy={}),
            "unknown policy key": lambda r: r["policy"].update(alpah=0.1),
            "unknown metric row key": lambda r: r["metrics"][0].update(extra=1),
            "bad decision": lambda r: r.update(decision="MAYBE"),
            "uppercase digest": lambda r: r.update(input_sha256=r["input_sha256"].upper()),
            "guardrail without margin": lambda r: r["input"]["metrics"]["refund_rate"].pop("margin"),
            "alpha out of range": lambda r: r["input"].setdefault("policy", {}).update(alpha=1),
            "wrong schema_version": lambda r: r.update(schema_version=2),
        }
        for name, edit in cases.items():
            edited = json.loads(json.dumps(record))
            edit(edited)
            with self.subTest(case=name):
                self.assertNotEqual(schema_validation.errors(edited, 3), [])
        # Unknown top-level members are ignored by the verifier, so the schema allows them.
        self.assertEqual(schema_validation.errors({**record, "note": "free text"}, 3), [])


class PackageDataTest(unittest.TestCase):
    def test_schema_files_are_declared_as_package_data(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"schema/*.json"', text)
        self.assertEqual(sorted(p.name for p in (ROOT / "expgate" / "schema").glob("*.json")),
                         ["decision.v2.json", "decision.v3.json"])


if __name__ == "__main__":
    unittest.main()
