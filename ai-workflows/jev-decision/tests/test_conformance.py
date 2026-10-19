import copy
import hashlib
import importlib.resources
import importlib.util
import io
import json
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from jevdecision import JevBackend, questions_from_spec
from jevdecision.__main__ import main as decide_main
from jevdecision.evaluation import main as eval_main
from jevdecision.jcs import canonicalize
from jevdecision.verify import _close, main as verify_main

try:
    import jsonschema
except ImportError:  # dev-only dependency; CI installs the pin from requirements-dev.txt
    jsonschema = None

COMPONENT = Path(__file__).resolve().parents[1]
CONFORMANCE = COMPONENT / "conformance"
MANIFEST = json.loads((CONFORMANCE / "manifest.json").read_text(encoding="utf-8"))
SCHEMAS = ("answer.v1.json", "answer.v2.json", "evaluation.v2.json", "provenance.v2.json")
EXIT_CODES = {"valid": 0, "tampered": 1, "invalid": 2}
EVALUATION_DERIVED = ("evaluation.json", "EVALUATION.md", "provenance.json")
EXAMPLES = COMPONENT / "examples"
SCHEMA_ID_BASE = "https://github.com/BichengWang/ai-decision-system/schema/jevdecision/"


def run_verify(command, path):
    assert command[0] == "jev-decision-verify"
    argv = [str(path) if part == "{path}" else part for part in command[1:]]
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = verify_main(argv)
    return code, out.getvalue() + err.getvalue()


def pointer(document, ref):
    value = document
    if ref == "":
        return value
    assert ref.startswith("/"), ref
    for token in ref[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def load_schema(name):
    return json.loads((COMPONENT / "jevdecision" / "schema" / name).read_text(encoding="utf-8"))


class ManifestTests(unittest.TestCase):
    def test_manifest_shape_and_files(self):
        self.assertEqual((MANIFEST["format"], MANIFEST["package"]), (1, "jevdecision"))
        listed, referenced = set(), set()
        for vector in MANIFEST["vectors"]:
            with self.subTest(path=vector["path"]):
                self.assertEqual(vector["verify"]["exit_code"], EXIT_CODES[vector["expect"]])
                self.assertIn("{path}", vector["verify"]["command"])
                self.assertTrue(vector["note"])
                self.assertTrue(vector["path"].startswith(vector["expect"] + "/"))
                path = CONFORMANCE / vector["path"]
                self.assertTrue(path.exists())
                listed.add(vector["path"])
                for digest in vector.get("digests", ()):
                    if "canonical_file" in digest:
                        referenced.add(digest["canonical_file"])
                    self.assertRegex(pointer(json.loads(self.read(vector, digest["document"])), digest["value"]),
                                     r"^[0-9a-f]{64}$")
                if vector["expect"] == "valid":
                    self.assertTrue(vector["digests"])
                    self.assertTrue(all(d["schema_valid"] for d in vector["documents"]))
        # Nothing in the tree is unaccounted for.
        for kind in EXIT_CODES:
            for path in (CONFORMANCE / kind).iterdir():
                relative = f"{kind}/{path.name}"
                self.assertTrue(relative in listed or relative in referenced, relative)
        for expect in EXIT_CODES:
            for family in ("answer-v2", "evaluation"):
                self.assertTrue(any(v["expect"] == expect and Path(v["path"]).name.startswith(family)
                                    for v in MANIFEST["vectors"]), (expect, family))
        self.assertTrue(any(v["path"] == "invalid/answer-v1.json" for v in MANIFEST["vectors"]))

    @staticmethod
    def read(vector, document):
        base = CONFORMANCE / vector["path"]
        return (base if document == "." else base / document).read_text(encoding="utf-8")

    def test_every_vector_verifies_with_its_exit_code(self):
        for vector in MANIFEST["vectors"]:
            with self.subTest(path=vector["path"]):
                code, output = run_verify(vector["verify"]["command"], CONFORMANCE / vector["path"])
                self.assertEqual(code, vector["verify"]["exit_code"], output)

    def test_every_digest_recomputes(self):
        counts = {"rfc8785": 0, "bytes": 0}
        for vector in MANIFEST["vectors"]:
            base = CONFORMANCE / vector["path"]
            for digest in vector.get("digests", ()):
                with self.subTest(path=vector["path"], value=digest["value"]):
                    document = json.loads(self.read(vector, digest["document"]))
                    recorded = pointer(document, digest["value"])
                    if digest["canonicalization"] == "bytes":
                        self.assertEqual(hashlib.sha256((base / digest["covers_file"]).read_bytes()).hexdigest(), recorded)
                    else:
                        self.assertEqual(digest["canonicalization"], "rfc8785")
                        covered = copy.deepcopy(pointer(document, digest["covers"]))
                        for member in digest["exclude"]:
                            del covered[member]
                        canonical = canonicalize(covered)
                        self.assertEqual((CONFORMANCE / digest["canonical_file"]).read_bytes(), canonical)
                        self.assertFalse(canonical.endswith(b"\n"))
                        self.assertEqual(hashlib.sha256(canonical).hexdigest(), recorded)
                    counts[digest["canonicalization"]] += 1
        self.assertGreater(counts["rfc8785"], 2)
        self.assertGreater(counts["bytes"], 20)

    def test_committed_tree_equals_a_fresh_generation(self):
        spec = importlib.util.spec_from_file_location("jev_conformance_generate", CONFORMANCE / "generate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fresh = module.generate()
        committed = {}
        for kind in (*EXIT_CODES, "."):
            base = CONFORMANCE if kind == "." else CONFORMANCE / kind
            for path in (base.rglob("*") if kind != "." else [CONFORMANCE / "manifest.json"]):
                if path.is_file():
                    committed[str(path.relative_to(CONFORMANCE))] = path.read_bytes()
        self.assertEqual(sorted(committed), sorted(fresh))
        for name in fresh:
            parts = Path(name).parts
            if len(parts) == 3 and parts[1].startswith("evaluation-") and parts[2] in EVALUATION_DERIVED:
                self.assert_same_up_to_platform_floats(parts[2], committed[name], fresh[name], name)
            else:
                self.assertEqual(committed[name], fresh[name], name)

    def assert_same_up_to_platform_floats(self, filename, committed, fresh, name):
        """evaluation.json holds math.log / NormalDist.inv_cdf results whose last digits differ between
        platforms (observed: macOS-generated vectors against Linux), and the hashes and digest line that
        cover it change with it. Compare the report with the verifier's tolerance and the rest exactly."""
        if filename == "EVALUATION.md":
            return  # rendered from the report and quoting its SHA-256
        left, right = json.loads(committed), json.loads(fresh)
        if filename == "provenance.json":
            for provenance in (left, right):
                for derived in ("evaluation.json", "EVALUATION.md"):
                    provenance.get("outputs", {}).pop(derived, None)
            self.assertEqual(left, right, name)
        else:
            self.assertTrue(_close(right, left, frozenset({"limit"})), name)


class PackageDataTests(unittest.TestCase):
    def test_schemas_ship_with_the_package_and_have_stable_ids(self):
        package = importlib.resources.files("jevdecision") / "schema"
        for name in SCHEMAS:
            schema = json.loads((package / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$id"], SCHEMA_ID_BASE + name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertRegex(schema["$comment"], r"RFC 8785|python-json-v1|Canonicalization: none")


@unittest.skipIf(jsonschema is None, "jsonschema is a dev-only dependency (requirements-dev.txt)")
class SchemaTests(unittest.TestCase):
    def validator(self, name):
        schema = load_schema(name)
        jsonschema.Draft202012Validator.check_schema(schema)
        return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)

    def test_documents_match_their_declared_validity(self):
        checked = 0
        for vector in MANIFEST["vectors"]:
            base = CONFORMANCE / vector["path"]
            for document in vector.get("documents", ()):
                path = base if document["path"] == "." else base / document["path"]
                schema_name = Path(document["schema"]).name
                errors = list(self.validator(schema_name).iter_errors(json.loads(path.read_text(encoding="utf-8"))))
                with self.subTest(path=str(path.relative_to(CONFORMANCE)), schema=schema_name):
                    self.assertEqual(not errors, document["schema_valid"], [e.message for e in errors][:3])
                checked += 1
        self.assertGreater(checked, 30)

    def test_records_produced_by_the_commands_validate(self):
        spec = json.loads((EXAMPLES / "support-ticket.json").read_text(encoding="utf-8"))
        response = json.loads((EXAMPLES / "support-ticket-responses.jsonl").read_text().splitlines()[0])["response"]
        backend = JevBackend(api_key="k", transport=lambda *a: copy.deepcopy(response), env={})
        for version in (1, 2):
            out = io.StringIO()
            with unittest.mock.patch("jevdecision.__main__.create_backend", return_value=backend), redirect_stdout(out):
                self.assertEqual(decide_main(["--questions", str(EXAMPLES / "support-ticket.json"), "--state", "x",
                                              "--schema-version", str(version)]), 0)
            self.validator(f"answer.v{version}.json").validate(json.loads(out.getvalue()))
        with tempfile.TemporaryDirectory() as tmp:
            for index, extra in enumerate(([], ["--require", str(EXAMPLES / "support-ticket-requirements.json")])):
                out_dir = Path(tmp) / f"run{index}"
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    eval_main(["--questions", str(EXAMPLES / "support-ticket.json"),
                               "--cases", str(EXAMPLES / "support-ticket-cases.jsonl"),
                               "--responses", str(EXAMPLES / "support-ticket-responses.jsonl"),
                               "--out", str(out_dir), *extra])
                for filename, schema in (("evaluation.json", "evaluation.v2.json"),
                                         ("provenance.json", "provenance.v2.json")):
                    self.validator(schema).validate(json.loads((out_dir / filename).read_text(encoding="utf-8")))
        self.assertEqual(len(questions_from_spec(spec)), 3)


if __name__ == "__main__":
    unittest.main()
