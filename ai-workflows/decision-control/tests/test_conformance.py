"""Run the package verifier over every conformance vector and check every recorded digest."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from decisioncontrol.jcs import canonicalize
from dc_support import jsonschema, load_schema, python_json_v1, validator

PROJECT = Path(__file__).resolve().parents[1]
CONFORMANCE = PROJECT / "conformance"
MANIFEST = json.loads((CONFORMANCE / "manifest.json").read_text(encoding="utf-8"))
EXIT = {"valid": 0, "tampered": 1, "invalid": 2}


def pointer(document, ref):
    """Resolve an RFC 6901 JSON Pointer."""
    if ref == "":
        return document
    assert ref.startswith("/"), ref
    for token in ref[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def load_generator():
    spec = importlib.util.spec_from_file_location("decisioncontrol_conformance_generate", CONFORMANCE / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vector_file(vector, name="."):
    base = CONFORMANCE / vector["path"]
    return base if name == "." else base / name


def verify(vector):
    path = str(vector_file(vector))
    command = [path if part == "{path}" else part for part in vector["verify"]["command"]]
    assert command[0] == "decision-control", command
    environment = {**os.environ, "PYTHONPATH": str(PROJECT)}
    return subprocess.run([sys.executable, "-m", "decisioncontrol", *command[1:]], cwd=CONFORMANCE,
                          env=environment, capture_output=True, text=True, timeout=60)


class ManifestTests(unittest.TestCase):
    def test_committed_tree_equals_a_fresh_generation(self):
        fresh = load_generator().generate()
        committed = {path.relative_to(CONFORMANCE).as_posix(): path.read_bytes()
                     for path in CONFORMANCE.rglob("*")
                     if path.is_file() and path.relative_to(CONFORMANCE).parts[0] in ("valid", "tampered", "invalid", "manifest.json")}
        self.assertEqual(sorted(committed), sorted(fresh))
        for path, content in fresh.items():
            with self.subTest(path=path):
                self.assertEqual(committed[path], content)

    def test_manifest_shape_and_coverage(self):
        self.assertEqual((MANIFEST["format"], MANIFEST["package"]), (1, "decisioncontrol"))
        paths = [vector["path"] for vector in MANIFEST["vectors"]]
        self.assertEqual(len(paths), len(set(paths)))
        coverage = set()
        for vector in MANIFEST["vectors"]:
            with self.subTest(path=vector["path"]):
                self.assertTrue(vector["path"].startswith(vector["expect"] + "/"))
                self.assertEqual(vector["verify"]["exit_code"], EXIT[vector["expect"]])
                self.assertIn("{path}", vector["verify"]["command"])
                self.assertTrue(vector["note"])
                self.assertTrue(vector_file(vector).is_file())
                self.assertEqual(bool(vector.get("digests")), vector["expect"] == "valid")
                for document in vector.get("documents", []):
                    self.assertEqual(document["path"], ".")
                    self.assertTrue((PROJECT / document["schema"]).is_file())
                    name = Path(document["schema"]).name
                    coverage.add((vector["expect"], name))
        for name in ("record.v4.json", "evaluation.v2.json"):
            for expect in EXIT:
                self.assertIn((expect, name), coverage)
        for name in ("record.v1.json", "record.v2.json", "record.v3.json", "evaluation.v1.json"):
            for expect in ("valid", "tampered"):
                self.assertIn((expect, name), coverage)


class VerifierTests(unittest.TestCase):
    def test_verifier_exit_codes(self):
        for vector in MANIFEST["vectors"]:
            with self.subTest(path=vector["path"]):
                completed = verify(vector)
                self.assertEqual(completed.returncode, vector["verify"]["exit_code"], completed.stderr)
                if vector["expect"] == "valid":
                    self.assertEqual(json.loads(completed.stdout)["valid"], True)
                else:
                    self.assertTrue(completed.stderr.startswith("decision-control: "), completed.stderr)

    def test_tampered_vectors_include_recomputed_checksums_the_replay_still_rejects(self):
        notes = [vector["note"] for vector in MANIFEST["vectors"] if vector["expect"] == "tampered"]
        self.assertTrue(any("self-approval" in note and "recompute" in note for note in notes))
        self.assertTrue(any("frozen policy" in note.lower() or "policy.min_probability" in note for note in notes))


class DigestTests(unittest.TestCase):
    def test_every_digest_entry(self):
        checked = 0
        for vector in MANIFEST["vectors"]:
            if vector["expect"] != "valid":
                continue
            for entry in vector["digests"]:
                with self.subTest(path=vector["path"], value=entry["value"]):
                    document = json.loads(vector_file(vector, entry["document"]).read_text(encoding="utf-8"))
                    recorded = pointer(document, entry["value"])
                    self.assertRegex(recorded, "^[0-9a-f]{64}$")
                    covered = pointer(document, entry["covers"])
                    for member in entry["exclude"]:
                        self.assertIn(member, covered)
                        covered = {key: value for key, value in covered.items() if key != member}
                    canonical_file = (CONFORMANCE / entry["canonical_file"]).read_bytes()
                    form = entry["canonicalization"]
                    expected = canonicalize(covered) if form == "rfc8785" else python_json_v1(covered)
                    self.assertIn(form, ("rfc8785", "python-json-v1"))
                    self.assertEqual(canonical_file, expected)
                    self.assertEqual(json.loads(canonical_file.decode("utf-8")), covered)
                    self.assertEqual(hashlib.sha256(canonical_file).hexdigest(), recorded)
                    self.assertFalse(canonical_file.endswith(b"\n"))
                    checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_whole_number_floats_distinguish_the_two_canonical_forms(self):
        by_path = {vector["path"]: vector for vector in MANIFEST["vectors"]}
        for stem, form in (("record-v4-whole-number-float-executed", b"1"), ("record-v3-whole-number-float-executed", b"1.0")):
            canonical = (CONFORMANCE / "valid" / f"{stem}.record.canonical").read_bytes()
            self.assertIn(b'"probability":' + form + b",", canonical)
            self.assertIn(f"valid/{stem}.json", by_path)


@unittest.skipIf(jsonschema is None, "jsonschema is a dev/CI-only dependency")
class VectorSchemaTests(unittest.TestCase):
    def test_documents_match_their_schema_expectation(self):
        checked = 0
        for vector in MANIFEST["vectors"]:
            for entry in vector.get("documents", []):
                document = json.loads(vector_file(vector, entry["path"]).read_text(encoding="utf-8"))
                with self.subTest(path=vector["path"]):
                    self.assertEqual(validator(Path(entry["schema"]).name).is_valid(document),
                                     entry["schema_valid"])
                    checked += 1
        self.assertGreaterEqual(checked, 50)

    def test_schema_files_referenced_by_the_manifest_exist_in_the_package(self):
        for vector in MANIFEST["vectors"]:
            for entry in vector.get("documents", []):
                self.assertEqual(load_schema(Path(entry["schema"]).name)["$id"].rsplit("/", 1)[1],
                                 Path(entry["schema"]).name)


if __name__ == "__main__":
    unittest.main()
