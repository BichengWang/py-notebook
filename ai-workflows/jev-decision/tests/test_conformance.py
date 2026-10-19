import copy
import hashlib
import importlib.resources
import importlib.util
import io
import json
import re
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from jevdecision import JevBackend, questions_from_spec
from jevdecision.__main__ import main as decide_main
from jevdecision.evaluation import main as eval_main, render_markdown
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


def load_generator():
    spec = importlib.util.spec_from_file_location("jev_conformance_generate", CONFORMANCE / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIGEST_LINE = re.compile(rb"(- evaluation\.json SHA-256: `)[0-9a-f]{64}(`)")
# Vectors whose provenance.json deliberately lists a hash that is not that of the committed file.
STALE_BY_DESIGN = {"evaluation-markdown-edited": ("EVALUATION.md", lambda data: data[:-1])}
# Every tampered and invalid evaluation vector is derived from this valid one by a named edit; only the
# edits that change EVALUATION.md appear here, all others leave it byte-identical to the source.
SOURCE_VECTOR = "evaluation-replay-gated"
MARKDOWN_EDITS = {"evaluation-markdown-edited": lambda data: data + b"\n"}


def compare_evaluation_directory(kind, directory, committed, fresh, source=None):
    """Compare a committed evaluation vector with a fresh generation, allowing only the platform
    difference of metric floats (evaluation.json compared with the verifier's tolerance) and what
    follows from it: the evaluation.json hash in provenance.json and the digest line of EVALUATION.md.

    EVALUATION.md must equal the fresh Markdown apart from that digest line, and for valid vectors must
    equal exactly what the renderer produces from the committed report and cases and the committed
    report's actual digest. For tampered and invalid vectors the digest line is not normalized at all:
    EVALUATION.md must equal the committed source vector's Markdown plus the vector's named edit,
    byte for byte. Both derived hashes in provenance.json must be the SHA-256 of the committed
    files, checked independently. Everything else is byte-exact.
    """
    name = f"{kind}/{directory}"
    for filename in committed:
        if filename not in ("evaluation.json", "EVALUATION.md", "provenance.json"):
            assert committed[filename] == fresh[filename], f"{name}/{filename}"
    if "evaluation.json" in committed:
        assert _close(json.loads(fresh["evaluation.json"]), json.loads(committed["evaluation.json"]),
                      frozenset({"limit"})), f"{name}/evaluation.json"
    if "EVALUATION.md" in committed and kind == "valid":
        assert DIGEST_LINE.sub(rb"\1X\2", committed["EVALUATION.md"]) == DIGEST_LINE.sub(
            rb"\1X\2", fresh["EVALUATION.md"]), f"{name}/EVALUATION.md"
    elif "EVALUATION.md" in committed:
        assert source is not None, f"{name}: needs the committed source vector"
        expected_markdown = MARKDOWN_EDITS.get(directory, lambda data: data)(source["EVALUATION.md"])
        assert committed["EVALUATION.md"] == expected_markdown, f"{name}/EVALUATION.md differs from the source vector"
    provenance, fresh_provenance = json.loads(committed["provenance.json"]), json.loads(fresh["provenance.json"])
    derived = {}
    for document in (provenance, fresh_provenance):
        outputs = document.get("outputs", {})
        for filename in ("evaluation.json", "EVALUATION.md"):
            if filename in outputs:
                derived.setdefault(id(document), {})[filename] = outputs[filename]["sha256"]
                outputs[filename]["sha256"] = "X"
    assert provenance == fresh_provenance, f"{name}/provenance.json"
    for filename, recorded in derived.get(id(provenance), {}).items():
        data = committed.get(filename)
        if data is None:
            continue
        if directory in STALE_BY_DESIGN and STALE_BY_DESIGN[directory][0] == filename:
            data = STALE_BY_DESIGN[directory][1](data)
        assert recorded == hashlib.sha256(data).hexdigest(), f"{name}: provenance hash of {filename}"
    if kind == "valid":
        digest = hashlib.sha256(committed["evaluation.json"]).hexdigest()
        # evaluation.json and cases.jsonl are written with sorted keys; the Markdown lists questions in
        # the order of the question file, so restore that order from the retained questions.json.
        order = list(json.loads(committed["questions.json"]))
        report = json.loads(committed["evaluation.json"])
        report["questions"] = {name: report["questions"][name] for name in order if name in report["questions"]}
        cases = []
        for line in committed["cases.jsonl"].decode("utf-8").splitlines():
            row = json.loads(line)
            if "questions" in row:
                row["questions"] = {name: row["questions"][name] for name in order if name in row["questions"]}
            cases.append(row)
        rendered = render_markdown(report, digest, cases)
        assert committed["EVALUATION.md"] == rendered.encode("utf-8"), f"{name}/EVALUATION.md is not the rendering"


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
        fresh = load_generator().generate()
        committed = {}
        for kind in (*EXIT_CODES, "."):
            base = CONFORMANCE if kind == "." else CONFORMANCE / kind
            for path in (base.rglob("*") if kind != "." else [CONFORMANCE / "manifest.json"]):
                if path.is_file():
                    committed[str(path.relative_to(CONFORMANCE))] = path.read_bytes()
        self.assertEqual(sorted(committed), sorted(fresh))
        directories = {}
        for name in fresh:
            parts = Path(name).parts
            if len(parts) == 3 and parts[1].startswith("evaluation-"):
                directories.setdefault(parts[:2], []).append(parts[2])
            else:
                self.assertEqual(committed[name], fresh[name], name)
        self.assertEqual(len(directories), 12)
        loaded = {key: {f: (CONFORMANCE / key[0] / key[1] / f).read_bytes() for f in filenames}
                  for key, filenames in directories.items()}
        source = loaded[("valid", SOURCE_VECTOR)]
        for (kind, directory), filenames in directories.items():
            compare_evaluation_directory(
                kind, directory, loaded[(kind, directory)],
                {f: fresh[f"{kind}/{directory}/{f}"] for f in filenames}, source)

    def test_substituted_markdown_with_a_matching_provenance_hash_is_caught(self):
        kind, directory = "valid", "evaluation-replay-gated"
        base = CONFORMANCE / kind / directory
        files = {path.name: path.read_bytes() for path in base.iterdir()}
        fresh = dict(files)
        compare_evaluation_directory(kind, directory, files, fresh)  # control: the real vector passes
        forged = dict(files)
        forged["EVALUATION.md"] = b"# Decision model evaluation: PASS\n\nsomething else entirely\n"
        provenance = json.loads(forged["provenance.json"])
        provenance["outputs"]["EVALUATION.md"]["sha256"] = hashlib.sha256(forged["EVALUATION.md"]).hexdigest()
        forged["provenance.json"] = json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with self.assertRaises(AssertionError):
            compare_evaluation_directory(kind, directory, forged, fresh)
        # The verifier agrees that the substituted directory is not the original.
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in forged.items():
                (Path(tmp) / name).write_bytes(data)
            self.assertEqual(run_verify(["jev-decision-verify", "--evaluation", "{path}"], Path(tmp))[0], 0)

    def test_zeroed_digest_line_in_a_tampered_vector_is_caught(self):
        source_dir = CONFORMANCE / "valid" / SOURCE_VECTOR
        source = {path.name: path.read_bytes() for path in source_dir.iterdir()}
        for kind, directory in (("tampered", "evaluation-responses-edited"), ("invalid", "evaluation-cases-unparseable")):
            base = CONFORMANCE / kind / directory
            files = {path.name: path.read_bytes() for path in base.iterdir()}
            compare_evaluation_directory(kind, directory, files, dict(files), source)  # control
            forged = dict(files)
            forged["EVALUATION.md"] = DIGEST_LINE.sub(rb"\g<1>" + b"0" * 64 + rb"\g<2>", files["EVALUATION.md"])
            self.assertNotEqual(forged["EVALUATION.md"], files["EVALUATION.md"])
            provenance = json.loads(forged["provenance.json"])
            provenance["outputs"]["EVALUATION.md"]["sha256"] = hashlib.sha256(forged["EVALUATION.md"]).hexdigest()
            forged["provenance.json"] = json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode("utf-8")
            with self.subTest(directory=directory), self.assertRaises(AssertionError):
                compare_evaluation_directory(kind, directory, forged, dict(files), source)

    def test_provenance_normalization_covers_only_the_two_derived_hashes(self):
        kind, directory = "valid", "evaluation-replay-gated"
        base = CONFORMANCE / kind / directory
        files = {path.name: path.read_bytes() for path in base.iterdir()}

        def with_provenance(edit):
            forged = dict(files)
            provenance = json.loads(forged["provenance.json"])
            edit(provenance)
            forged["provenance.json"] = json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return forged

        edits = {
            "derived hash not matching the file": lambda p: p["outputs"]["EVALUATION.md"].update(sha256="0" * 64),
            "other hash changed": lambda p: p["outputs"]["responses.jsonl"].update(sha256="0" * 64),
            "derived entry removed": lambda p: p["outputs"].pop("EVALUATION.md"),
            "extra key in a derived entry": lambda p: p["outputs"]["evaluation.json"].update(note="x"),
        }
        for name, edit in edits.items():
            with self.subTest(name=name), self.assertRaises(AssertionError):
                compare_evaluation_directory(kind, directory, with_provenance(edit), files)

    def test_a_generator_that_renders_junk_markdown_is_caught(self):
        generator = load_generator()
        with unittest.mock.patch("jevdecision.evaluation.render_markdown", return_value="junk\n"):
            junk = generator.generate()
        name = "valid/evaluation-replay-gated/EVALUATION.md"
        self.assertEqual(junk[name], b"junk\n")
        directory = "evaluation-replay-gated"
        base = CONFORMANCE / "valid" / directory
        committed = {path.name: path.read_bytes() for path in base.iterdir()}
        fresh = {f: junk[f"valid/{directory}/{f}"] for f in committed}
        with self.assertRaises(AssertionError):
            compare_evaluation_directory("valid", directory, committed, fresh)


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
