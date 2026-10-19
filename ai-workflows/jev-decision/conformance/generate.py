"""Generate the Jev conformance vectors and manifest.json (standard library only, deterministic).

    python3 conformance/generate.py            # rewrite conformance/{valid,tampered,invalid} and manifest.json

Every vector is derived from fixed inputs: the example questions, cases and responses in
`examples/`, hand-written provider responses below, and named edits recorded in each vector's
`note`. Nothing here is output from a live provider. `tests/test_conformance.py` asserts that the
committed tree equals a fresh generation. Regenerate after changing the record formats or the
package version (records carry `produced_by.version`).
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT.parent
sys.path.insert(0, str(COMPONENT))

from jevdecision import APIError, JevBackend, OpenAIDecisionsBackend, questions_from_spec  # noqa: E402
from jevdecision.evaluation import main as evaluate_main  # noqa: E402
from jevdecision.jcs import canonicalize  # noqa: E402
from jevdecision.records import DIGEST_FIELD, answer_record, dumps_record, record_digest  # noqa: E402

EXAMPLES = COMPONENT / "examples"
QUESTIONS_FILE = EXAMPLES / "support-ticket.json"
CASES_FILE = EXAMPLES / "support-ticket-cases.jsonl"
RESPONSES_FILE = EXAMPLES / "support-ticket-responses.jsonl"
REQUIRE_FILE = EXAMPLES / "support-ticket-requirements.json"
STATE = "Help! My payouts have been failing for 3 days."
SCHEMA_DIR = "jevdecision/schema/"
VERIFY = "jev-decision-verify"

# Hand-written responses in the providers' formats; synthetic, not provider output.
JEV_RESPONSE = json.loads(RESPONSES_FILE.read_text(encoding="utf-8").splitlines()[0])["response"]
OPENAI_RESPONSE = {
    "model": "decisions-example", "id": "example-openai-1", "usage": {"total_tokens": 7},
    "answers": [
        {"type": "predicate", "name": "refund", "probability": 0.12},
        {"type": "choice", "name": "department", "value": "technical",
         "probabilities": [{"value": "billing", "probability": 0.08}, {"value": "technical", "probability": 0.85},
                           {"value": "sales", "probability": 0.07}]},
        {"type": "score", "name": "frustration", "score": 1, "probabilities": [
            {"label": "Calm", "probability": 0.0}, {"label": "Frustrated", "probability": 1.0},
            {"label": "Very angry", "probability": 0.0}]},
    ],
}
# Exercises canonical number formatting (1e-7, 5e-324, integral floats), non-ASCII text and
# UTF-16 member ordering (the emoji and the Hebrew letter sort differently by code point).
CANON_QUESTIONS = {
    "tone": {"type": "choice", "instructions": "Which tone fits? Réponse: ✓ 日本語",
             "criteria": {"a": "Plain", "é": "Accent", "€": "Euro sign", "😀": "Emoji", "\ufb33": "Hebrew dagesh"}},
    "urgency": {"type": "score", "instructions": "How urgent is it?", "criteria": ["low", "high"]},
    "rare": {"type": "noul", "instructions": "Is this a rare event?"},
    "refund": {"type": "noul", "instructions": "Is the customer asking for a refund?"},
}
CANON_RESPONSE = {
    "model": "jev-example", "id": "example-canon-1", "usage": {"credits_used": 12.0},
    "answers": {
        "tone": {"type": "choice", "choice": "a", "probabilities": {
            "a": 0.5, "é": 0.25, "€": 0.125, "😀": 0.0625, "\ufb33": 0.0625}},
        "urgency": {"type": "score", "score": 1.0, "probabilities": [1e-07, 0.9999999]},
        "rare": {"type": "noul", "noul": 5e-324},
        "refund": {"type": "refusal"},
    },
}


class Tree:
    """Files and manifest entries for one generation."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.vectors: list[dict] = []

    def add_file(self, path, data):
        assert path not in self.files, path
        self.files[path] = data if isinstance(data, bytes) else data.encode("utf-8")

    def add_vector(self, path, expect, command, note, documents=None, digests=None):
        vector = {"path": path, "expect": expect,
                  "verify": {"command": command, "exit_code": {"valid": 0, "tampered": 1, "invalid": 2}[expect]}}
        if documents:
            vector["documents"] = documents
        if digests:
            vector["digests"] = digests
        vector["note"] = note
        self.vectors.append(vector)

    def manifest(self):
        return json.dumps({"format": 1, "package": "jevdecision", "vectors": self.vectors},
                          indent=2, ensure_ascii=False) + "\n"


def append_newline(data):
    """The named edit of tampered/evaluation-markdown-edited: one newline appended to EVALUATION.md."""
    return data + b"\n"


def document(schema, valid, path="."):
    return {"path": path, "schema": SCHEMA_DIR + schema, "schema_valid": valid}


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


# Answer records ------------------------------------------------------------

def make_answer(spec, response, backend_class=JevBackend):
    questions = questions_from_spec(spec)
    backend = backend_class(api_key="offline", transport=lambda *args: copy.deepcopy(response), env={})
    return answer_record(backend.decide(STATE, questions), questions)


def line(record):
    return dumps_record(record) + "\n"


def reseal(record):
    record[DIGEST_FIELD] = record_digest(record)
    return record


def add_answers(tree):
    support = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    base = {
        "answer-v2-jev": (make_answer(support, JEV_RESPONSE), "Jev-format response, noul/choice/score answers"),
        "answer-v2-openai": (make_answer(support, OPENAI_RESPONSE, OpenAIDecisionsBackend),
                             "OpenAI Decisions list-format response; backend openai"),
        "answer-v2-canonical-numbers": (make_answer(CANON_QUESTIONS, CANON_RESPONSE),
                                        "refusal, 1e-7, 5e-324, integral floats written as integers, "
                                        "non-ASCII text and UTF-16 key ordering in the canonical form"),
    }
    schema = "answer.v2.json"
    for name, (record, note) in base.items():
        path = f"valid/{name}.json"
        tree.add_file(path, line(record))
        covered = {k: v for k, v in record.items() if k != DIGEST_FIELD}
        canonical = f"valid/{name}.canonical"
        tree.add_file(canonical, canonicalize(covered))
        assert sha(canonicalize(covered)) == record[DIGEST_FIELD]
        tree.add_vector(path, "valid", [VERIFY, "{path}"], note, [document(schema, True)], [{
            "document": ".", "value": "/record_sha256", "covers": "", "exclude": [DIGEST_FIELD],
            "canonicalization": "rfc8785", "canonical_file": canonical}])

    jev = base["answer-v2-jev"][0]

    def edited(edit, sealed=False):
        record = copy.deepcopy(jev)
        edit(record)
        return reseal(record) if sealed else record

    tampered = {
        "answer-v2-answer-edited": (edited(lambda r: r["answers"]["refund"].update(probability=0.99)),
                                    "answers.refund.probability changed from 0.08 to 0.99; record_sha256 left"),
        "answer-v2-answer-edited-resealed": (
            edited(lambda r: r["answers"]["refund"].update(probability=0.99), True),
            "answers.refund.probability changed to 0.99 and record_sha256 recomputed; the embedded response "
            "no longer reproduces the answer"),
        "answer-v2-response-edited": (edited(lambda r: r["response"]["answers"]["refund"].update(noul=0.8)),
                                      "response.answers.refund.noul changed from 0.08 to 0.8; record_sha256 left"),
        "answer-v2-response-edited-resealed": (
            edited(lambda r: r["response"]["answers"]["refund"].update(noul=0.8), True),
            "response.answers.refund.noul changed to 0.8 and record_sha256 recomputed; the recorded answer no "
            "longer follows from the response"),
        "answer-v2-question-edited": (
            edited(lambda r: r["questions"]["refund"].update(instructions="Is the customer angry?")),
            "questions.refund.instructions changed; record_sha256 left"),
        "answer-v2-id-edited-resealed": (edited(lambda r: r.update(id="forged-id"), True),
                                         "id changed to forged-id and record_sha256 recomputed; the response id differs"),
    }
    for name, (record, note) in tampered.items():
        path = f"tampered/{name}.json"
        tree.add_file(path, line(record))
        tree.add_vector(path, "tampered", [VERIFY, "{path}"], note, [document(schema, True)])

    # Invalid inputs.
    from jevdecision import DecisionModel
    v1 = DecisionModel(JevBackend(api_key="offline", transport=lambda *a: copy.deepcopy(JEV_RESPONSE), env={})
                       ).decide(STATE, questions_from_spec(support)).to_dict()
    tree.add_file("invalid/answer-v1.json", compact(v1) + "\n")
    tree.add_vector("invalid/answer-v1.json", "invalid", [VERIFY, "{path}"],
                    "schema 1 answer record (0.1.0 shape): readable, but it embeds no questions or response, so it "
                    "is unverifiable", [document("answer.v1.json", True)])

    def invalid(name, record_or_text, note, schema_valid=None):
        path = f"invalid/{name}.json"
        text = record_or_text if isinstance(record_or_text, str) else line(record_or_text)
        tree.add_file(path, text)
        tree.add_vector(path, "invalid", [VERIFY, "{path}"], note,
                        None if schema_valid is None else [document(schema, schema_valid)])

    schema3 = edited(lambda r: r.update(schema_version=3))
    invalid("answer-v2-unsupported-schema", schema3, "schema_version changed to 3", False)
    missing = edited(lambda r: r.pop("questions"))
    invalid("answer-v2-missing-questions", missing, "questions member removed", False)
    text = line(jev)
    invalid("answer-v2-duplicate-key", text.rstrip("\n")[:-1] + ',"id":"example-t01"}\n',
            "a second id member appended to the top-level object (duplicate object keys)")
    invalid("answer-v2-non-finite", text.replace('"noul":0.08', '"noul":NaN', 1),
            "response.answers.refund.noul replaced by the non-JSON literal NaN")
    invalid("answer-v2-oversized-integer", text.replace('"response":{', '"response":{"counter":1152921504606846976,', 1),
            "response.counter = 2^60 inserted: outside the I-JSON safe range, so the record cannot be "
            "canonicalized; record_sha256 left", True)
    unnormalized = edited(lambda r: r["questions"]["refund"].update(type="predicate"))
    invalid("answer-v2-unnormalized-questions", unnormalized,
            "questions.refund.type changed to the alias predicate (not the normalized question map form)", False)


# Evaluation directories ----------------------------------------------------

def run_eval(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = evaluate_main([str(arg) for arg in args])
    return code


def read_dir(path):
    return {item.name: item.read_bytes() for item in sorted(path.iterdir())}


def reseal_dir(files, mutate=None):
    """Rewrite provenance.json so every listed output hash matches the files, then apply `mutate`."""
    provenance = json.loads(files["provenance.json"])
    for name in provenance["outputs"]:
        if name in files:
            provenance["outputs"][name]["sha256"] = sha(files[name])
    if mutate:
        mutate(provenance)
    files["provenance.json"] = compact(provenance).encode("utf-8")


def eval_digests(files, extra):
    """`bytes` digest entries for every hash in provenance.json whose file is in the vector directory."""
    provenance = json.loads(files["provenance.json"])
    entries = []
    for name in provenance["outputs"]:
        entries.append({"document": "provenance.json", "value": f"/outputs/{name}/sha256",
                        "canonicalization": "bytes", "covers_file": name})
    for role, entry in provenance["inputs"].items():
        if entry is not None:
            covers = {"questions": "questions.json", "requirements": "requirements.json"}.get(role, extra.get(role))
            entries.append({"document": "provenance.json", "value": f"/inputs/{role}/sha256",
                            "canonicalization": "bytes", "covers_file": covers})
            assert sha(files[covers]) == entry["sha256"], role
    return entries


def add_dir(tree, kind, name, files, command_note, digests=None, documents=None):
    for filename, data in files.items():
        tree.add_file(f"{kind}/{name}/{filename}", data)
    tree.add_vector(f"{kind}/{name}", kind, [VERIFY, "--evaluation", "{path}"], command_note, documents, digests)


EVAL_DOCUMENTS = [document("evaluation.v2.json", True, "evaluation.json"),
                  document("provenance.v2.json", True, "provenance.json")]


def add_evaluations(tree):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        assert run_eval(["--questions", QUESTIONS_FILE, "--cases", CASES_FILE, "--responses", RESPONSES_FILE,
                         "--require", REQUIRE_FILE, "--out", tmp / "gated"]) == 0
        assert run_eval(["--questions", QUESTIONS_FILE, "--cases", CASES_FILE, "--responses", RESPONSES_FILE,
                         "--out", tmp / "ungated"]) == 3

        three = tmp / "three-cases.jsonl"
        three.write_text("".join(CASES_FILE.read_text(encoding="utf-8").splitlines(True)[:3]), encoding="utf-8")
        queue = [JEV_RESPONSE, APIError("HTTP 500 from provider", 500), {"answers": {"refund": {"noul": 4}}}]

        def transport(*args):
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return copy.deepcopy(item)

        backend = JevBackend(api_key="offline", transport=transport, sleep=lambda _: None, max_retries=0, env={})
        with unittest.mock.patch("jevdecision.evaluation.create_backend", return_value=backend):
            assert run_eval(["--questions", QUESTIONS_FILE, "--cases", three, "--out", tmp / "live"]) == 1

        gated, ungated, live = (read_dir(tmp / name) for name in ("gated", "ungated", "live"))
        inputs = {"cases": CASES_FILE.read_bytes(), "responses": RESPONSES_FILE.read_bytes()}
        extra_names = {"cases": "input-cases.jsonl", "responses": "input-responses.jsonl"}

        def with_inputs(files, cases=None):
            full = dict(files)
            full["input-cases.jsonl"] = inputs["cases"] if cases is None else cases
            if "input-responses.jsonl" not in full and json.loads(files["provenance.json"])["inputs"]["responses"]:
                full["input-responses.jsonl"] = inputs["responses"]
            return full

        gated_full, ungated_full = with_inputs(gated), with_inputs(ungated)
        live_full = with_inputs(live, three.read_bytes())
        live_full.pop("input-responses.jsonl", None)

        valid = (
            ("evaluation-replay-gated", gated_full, "replay of the 12 example cases with requirements (PASS); "
             "inputs retained for the cases and responses hashes"),
            ("evaluation-replay-ungated", ungated_full, "replay without requirements (UNGATED); no "
             "requirements.json and inputs.requirements null"),
            ("evaluation-live-failures", live_full, "recorded live run of 3 cases: one answered, one failed request "
             "(error text only in evaluation.json), one unparseable response"),
        )
        for name, files, note in valid:
            add_dir(tree, "valid", name, files, note, eval_digests(files, extra_names), EVAL_DOCUMENTS)

        # Tampered copies of the gated replay.
        def flip(data, offset=20):
            return data[:offset] + bytes([data[offset] ^ 1]) + data[offset + 1:]

        files = dict(gated_full)
        files["responses.jsonl"] = flip(files["responses.jsonl"])
        add_dir(tree, "tampered", "evaluation-responses-edited", files,
                "one byte of responses.jsonl flipped; provenance.json left", None, EVAL_DOCUMENTS)

        files = dict(gated_full)
        report = json.loads(files["evaluation.json"])
        report["status"] = "FAIL"
        files["evaluation.json"] = compact(report).encode("utf-8")
        reseal_dir(files)
        add_dir(tree, "tampered", "evaluation-report-resealed", files,
                "evaluation.json status changed from PASS to FAIL and its provenance hash recomputed; re-scoring "
                "disagrees", None, EVAL_DOCUMENTS)

        files = dict(gated_full)
        spec = json.loads(files["requirements.json"])
        spec["max_error_rate"] = 0.5
        files["requirements.json"] = compact(spec).encode("utf-8")
        report = json.loads(files["evaluation.json"])
        report["requirements"][0]["limit"] = 0.5
        files["evaluation.json"] = compact(report).encode("utf-8")

        def rehash_requirements(provenance):
            provenance["inputs"]["requirements"]["sha256"] = sha(files["requirements.json"])

        reseal_dir(files, rehash_requirements)
        add_dir(tree, "tampered", "evaluation-requirements-edited-resealed", files,
                "retained requirements.json loosened (max_error_rate 0.5) and the error_rate limit, "
                "evaluation.json and provenance hashes rewritten consistently; the recorded check results no "
                "longer follow from the responses", None, EVAL_DOCUMENTS)

        files = dict(gated_full)
        del files["cases.jsonl"]
        add_dir(tree, "tampered", "evaluation-file-missing", files,
                "cases.jsonl removed although provenance.json lists it", None, EVAL_DOCUMENTS)

        files = dict(gated_full)
        files["EVALUATION.md"] = append_newline(files["EVALUATION.md"])
        add_dir(tree, "tampered", "evaluation-markdown-edited", files,
                "a newline appended to EVALUATION.md; provenance.json left", None, EVAL_DOCUMENTS)

        # Invalid directories.
        files = dict(gated_full)
        provenance = json.loads(files["provenance.json"])
        provenance["schema_version"] = 1
        files["provenance.json"] = compact(provenance).encode("utf-8")
        add_dir(tree, "invalid", "evaluation-provenance-schema-1", files,
                "provenance.json schema_version changed to 1 (unsupported)",
                None, [document("provenance.v2.json", False, "provenance.json")])

        files = dict(gated_full)
        text = files["provenance.json"].decode("utf-8")
        files["provenance.json"] = (text[:-1] + ',"response_mode":"replay"}').encode("utf-8")
        add_dir(tree, "invalid", "evaluation-provenance-duplicate-key", files,
                "a second response_mode member appended to provenance.json (duplicate object keys)")

        files = dict(gated_full)
        files["cases.jsonl"] = b"{\n"
        reseal_dir(files)
        add_dir(tree, "invalid", "evaluation-cases-unparseable", files,
                "cases.jsonl replaced by an unparseable line and its provenance hash recomputed",
                None, EVAL_DOCUMENTS)

        files = dict(gated_full)
        provenance = json.loads(files["provenance.json"])
        del provenance["outputs"]["cases.jsonl"]
        files["provenance.json"] = compact(provenance).encode("utf-8")
        add_dir(tree, "invalid", "evaluation-provenance-missing-output", files,
                "the cases.jsonl entry removed from provenance.json outputs",
                None, [document("provenance.v2.json", False, "provenance.json")])


def generate():
    tree = Tree()
    add_answers(tree)
    add_evaluations(tree)
    order = {"valid": 0, "tampered": 1, "invalid": 2}
    tree.vectors.sort(key=lambda vector: (order[vector["expect"]], vector["path"]))
    tree.add_file("manifest.json", tree.manifest())
    return tree.files


def write(target):
    for kind in ("valid", "tampered", "invalid"):
        shutil.rmtree(target / kind, ignore_errors=True)
    for relative, data in generate().items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


if __name__ == "__main__":
    write(ROOT)
