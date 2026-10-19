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


EVALUATION_RULE_FILES = ("evaluation.json", "EVALUATION.md", "provenance.json")


def check_derived_hashes(name, directory, files):
    """provenance.json's hashes of evaluation.json and EVALUATION.md must be those files' SHA-256, except
    where the vector deliberately leaves a stale one. Returns provenance.json with those two values masked."""
    provenance = json.loads(files["provenance.json"])
    outputs = provenance.get("outputs", {})
    for filename in ("evaluation.json", "EVALUATION.md"):
        if filename not in outputs:
            continue
        recorded, outputs[filename]["sha256"] = outputs[filename]["sha256"], "X"
        data = files.get(filename)
        if data is None:
            continue
        if directory in STALE_BY_DESIGN and STALE_BY_DESIGN[directory][0] == filename:
            data = STALE_BY_DESIGN[directory][1](data)
        assert recorded == hashlib.sha256(data).hexdigest(), f"{name}: provenance hash of {filename}"
    return provenance


def compare_evaluation_directory(kind, directory, committed, fresh, source=None, fresh_source=None):
    """Compare a committed evaluation vector with a fresh generation, allowing only the platform
    difference of metric floats and what follows from it. Returns the filenames covered by a rule
    instead of byte equality.

    - evaluation.json: compared with the verifier's tolerance.
    - EVALUATION.md, valid vectors: equal to the fresh Markdown apart from its digest line, and the
      committed one exactly the rendering of the committed report and cases with the committed report's
      actual digest. Tampered and invalid vectors: the digest line is not normalized; in BOTH trees the
      Markdown equals that tree's own source vector's Markdown plus the vector's named edit, byte for byte.
    - provenance.json: equal apart from the two hashes derived from the files above; in BOTH trees those
      two hashes are the SHA-256 of that tree's files (checked independently), except for the deliberate
      stale hash.
    - every other file is byte-equal.
    """
    name = f"{kind}/{directory}"
    for filename in committed:
        if filename not in EVALUATION_RULE_FILES:
            assert committed[filename] == fresh[filename], f"{name}/{filename}"
    if "evaluation.json" in committed:
        assert _close(json.loads(fresh["evaluation.json"]), json.loads(committed["evaluation.json"]),
                      frozenset({"limit"})), f"{name}/evaluation.json"
    if "EVALUATION.md" in committed and kind == "valid":
        assert DIGEST_LINE.sub(rb"\1X\2", committed["EVALUATION.md"]) == DIGEST_LINE.sub(
            rb"\1X\2", fresh["EVALUATION.md"]), f"{name}/EVALUATION.md"
    elif "EVALUATION.md" in committed:
        assert source is not None and fresh_source is not None, f"{name}: needs the source vector of each tree"
        edit = MARKDOWN_EDITS.get(directory, lambda data: data)
        assert committed["EVALUATION.md"] == edit(source["EVALUATION.md"]), \
            f"{name}/EVALUATION.md (committed) differs from the source vector plus its named edit"
        assert fresh["EVALUATION.md"] == edit(fresh_source["EVALUATION.md"]), \
            f"{name}/EVALUATION.md (fresh) differs from the source vector plus its named edit"
    assert check_derived_hashes(name, directory, committed) == check_derived_hashes(name, directory, fresh), \
        f"{name}/provenance.json"
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
    return {filename for filename in committed if filename in EVALUATION_RULE_FILES}


def read_committed_tree():
    committed = {}
    for kind in (*EXIT_CODES, "."):
        base = CONFORMANCE if kind == "." else CONFORMANCE / kind
        for path in (base.rglob("*") if kind != "." else [CONFORMANCE / "manifest.json"]):
            if path.is_file():
                committed[str(path.relative_to(CONFORMANCE))] = path.read_bytes()
    return committed


def compare_trees(committed, fresh):
    """Assert the fresh tree equals the committed one under the rules above; return the covered paths."""
    assert sorted(committed) == sorted(fresh), "the file sets differ"
    directories = {}
    covered = set()
    for name in fresh:
        parts = Path(name).parts
        if len(parts) == 3 and parts[1].startswith("evaluation-"):
            directories.setdefault(parts[:2], []).append(parts[2])
        else:
            assert committed[name] == fresh[name], name
    assert len(directories) == 12
    source_key = ("valid", SOURCE_VECTOR)

    def files_of(tree, key):
        return {f: tree[f"{key[0]}/{key[1]}/{f}"] for f in directories[key]}

    for key in directories:
        for filename in compare_evaluation_directory(
                key[0], key[1], files_of(committed, key), files_of(fresh, key),
                files_of(committed, source_key), files_of(fresh, source_key)):
            covered.add(f"{key[0]}/{key[1]}/{filename}")
    return covered


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
        compare_trees(read_committed_tree(), load_generator().generate())

    def test_every_fresh_file_is_byte_equal_or_covered_by_a_checked_rule(self):
        committed, fresh = read_committed_tree(), load_generator().generate()
        covered = compare_trees(committed, fresh)
        self.assertEqual(len(fresh), len(committed))
        unequal = {name for name in fresh if committed[name] != fresh[name]}
        self.assertLessEqual(unequal, covered, "files that differ but have no rule")
        self.assertTrue(covered)
        for name in covered:
            self.assertIn(Path(name).name, EVALUATION_RULE_FILES)
        # A difference outside the rules is not silently skipped.
        for victim in ("valid/evaluation-replay-gated/cases.jsonl", "tampered/answer-v2-id-edited-resealed.json",
                       "manifest.json", "valid/answer-v2-jev.canonical"):
            changed = dict(fresh)
            changed[victim] = fresh[victim] + b" "
            with self.subTest(victim=victim), self.assertRaises(AssertionError):
                compare_trees(committed, changed)
        missing = dict(fresh)
        del missing["manifest.json"]
        with self.assertRaises(AssertionError):
            compare_trees(committed, missing)

    def test_a_changed_named_edit_in_the_generator_is_caught(self):
        committed = read_committed_tree()
        generator = load_generator()
        with unittest.mock.patch.object(generator, "append_newline", lambda data: data + b"\n\n"):
            fresh = generator.generate()
        name = "tampered/evaluation-markdown-edited/EVALUATION.md"
        self.assertNotEqual(committed[name], fresh[name])
        with self.assertRaises(AssertionError):
            compare_trees(committed, fresh)

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
            compare_evaluation_directory(kind, directory, files, dict(files), source, source)  # control
            forged = dict(files)
            forged["EVALUATION.md"] = DIGEST_LINE.sub(rb"\g<1>" + b"0" * 64 + rb"\g<2>", files["EVALUATION.md"])
            self.assertNotEqual(forged["EVALUATION.md"], files["EVALUATION.md"])
            provenance = json.loads(forged["provenance.json"])
            provenance["outputs"]["EVALUATION.md"]["sha256"] = hashlib.sha256(forged["EVALUATION.md"]).hexdigest()
            forged["provenance.json"] = json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode("utf-8")
            with self.subTest(directory=directory), self.assertRaises(AssertionError):
                compare_evaluation_directory(kind, directory, forged, dict(files), source, source)

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
