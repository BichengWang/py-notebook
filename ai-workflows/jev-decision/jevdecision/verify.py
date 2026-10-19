"""Verify Jev records offline, from the records alone.

    jev-decision-verify answer.json
    jev-decision-verify --evaluation eval-run

An answer record (schema 2) is checked by re-parsing its embedded raw provider
response with its embedded question definitions, comparing the typed answers,
response id, model and usage with the recorded ones, and recomputing
`record_sha256`. Schema 1 answer records hold no response and cannot be verified.

An evaluation directory is checked by hashing every retained file listed in
`provenance.json` and then re-scoring the retained `responses.jsonl` against the
retained `questions.json`, the retained `requirements.json` and the expected answers recorded in
`cases.jsonl`. Nothing is sent to a provider. Recomputed metric floats must agree with
`evaluation.json` within a relative 1e-9 (math.log and NormalDist.inv_cdf differ in the last digits
between platform math libraries); everything else compares exactly. Hashes detect change; they do not
authenticate who wrote a record, and a record edited together with its digests
cannot be told from the original except through the re-derived content.

Exit codes: 0 verified, 1 mismatch, 2 malformed, unreadable, unsupported or
unverifiable (for example schema 1) input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .backends import BACKENDS, create_backend
from .errors import DecisionError
from .evaluation import Case, _expected, case_results, evaluate, replay
from .jcs import canonicalize
from .questions import check_question_set, questions_from_spec
from .records import DIGEST_FIELD, SHA256_RE, loads_strict, question_spec, record_digest

ANSWER_FIELDS = frozenset({"schema_version", "produced_by", "backend", "model", "id", "usage",
                           "answers", "questions", "response", DIGEST_FIELD})
PROVENANCE_FIELDS = frozenset({"schema_version", "produced_by", "response_mode", "response_origin",
                               "inputs", "outputs"})
INPUT_NAMES = frozenset({"questions", "cases", "requirements", "responses"})
OUTPUT_NAMES = ("evaluation.json", "EVALUATION.md", "responses.jsonl", "cases.jsonl")
# Inputs retained next to the outputs, by provenance input name.
RETAINED_INPUTS = {"questions": "questions.json", "requirements": "requirements.json"}
EVALUATION_FIELDS = frozenset({"schema_version", "produced_by", "jevdecision_version", "backend", "model",
                               "source", "cases", "answered", "errors", "error_rate", "questions",
                               "requirements", "status"})


def _differs(left: Any, right: Any) -> bool:
    return canonicalize(left) != canonicalize(right)


def _is_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _check_fields(record: dict, expected: frozenset, what: str) -> None:
    missing, extra = sorted(expected - set(record)), sorted(set(record) - expected)
    if missing or extra:
        raise ValueError(f"{what} fields differ from the schema: missing {missing}, unexpected {extra}")


def _check_producer(producer: Any, what: str) -> None:
    if (not isinstance(producer, dict) or set(producer) != {"name", "version"}
            or producer["name"] != "jevdecision" or not isinstance(producer["version"], str)):
        raise ValueError(f"{what}: invalid produced_by")


# Answer records ------------------------------------------------------------

def verify_answer_record(record: Any) -> list[str]:
    """Return mismatched fields; raise ValueError for invalid, unsupported or schema 1 records."""
    if not isinstance(record, dict):
        raise ValueError("answer record must be a JSON object")
    schema = record.get("schema_version")
    if _is_int(schema, 1):
        raise ValueError("schema 1 cannot be verified: no embedded questions or response")
    if not _is_int(schema, 2):
        raise ValueError("unsupported schema_version; expected 2")
    _check_fields(record, ANSWER_FIELDS, "answer record")
    _check_producer(record["produced_by"], "answer record")
    if record["backend"] not in BACKENDS:
        raise ValueError(f"unknown backend {record['backend']!r}")
    digest = record[DIGEST_FIELD]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError(f"{DIGEST_FIELD} must be 64 lowercase hex digits")
    for field in ("answers", "usage", "response"):
        if not isinstance(record[field], dict):
            raise ValueError(f"{field} must be an object")
    questions = check_question_set(questions_from_spec(record["questions"]))
    if _differs(record["questions"], question_spec(questions)):
        raise ValueError("questions are not in the normalized question map form")

    mismatches = []
    if record_digest(record) != digest:
        mismatches.append(DIGEST_FIELD)
    backend = create_backend(record["backend"], api_key="offline", env={})
    try:
        decision = backend.parse_response(record["response"], questions)
    except DecisionError as exc:
        # The producer only records responses that parsed, so the evidence no longer supports the record.
        return mismatches + [f"response (does not parse under the embedded questions: {exc})"]
    if _differs(record["answers"], {name: answer.to_dict() for name, answer in decision.answers.items()}):
        mismatches.append("answers")
    if "model" in record["response"]:
        model_differs = _differs(record["model"], decision.model)
    else:  # the requested model is not part of the response and cannot be re-derived
        model_differs = not isinstance(record["model"], str) or not record["model"]
    if model_differs:
        mismatches.append("model")
    if _differs(record["id"], decision.id):
        mismatches.append("id")
    if _differs(record["usage"], decision.usage):
        mismatches.append("usage")
    return mismatches


# Evaluation directories ----------------------------------------------------

def _sha256_entry(value: Any, where: str) -> str:
    if not isinstance(value, dict) or set(value) != {"sha256"} or not isinstance(value["sha256"], str) \
            or not SHA256_RE.fullmatch(value["sha256"]):
        raise ValueError(f"provenance {where}: expected {{\"sha256\": <64 lowercase hex digits>}}")
    return value["sha256"]


def _check_provenance(provenance: Any) -> dict[str, str]:
    """Validate provenance.json; return {retained file name: sha256}."""
    if not isinstance(provenance, dict):
        raise ValueError("provenance.json must be a JSON object")
    if not _is_int(provenance.get("schema_version"), 2):
        raise ValueError("unsupported provenance schema_version; expected 2")
    _check_fields(provenance, PROVENANCE_FIELDS, "provenance")
    _check_producer(provenance["produced_by"], "provenance")
    if provenance["response_mode"] not in ("live", "replay") or not isinstance(provenance["response_origin"], str):
        raise ValueError("provenance: invalid response_mode or response_origin")
    inputs = provenance["inputs"]
    if not isinstance(inputs, dict) or set(inputs) != INPUT_NAMES:
        raise ValueError(f"provenance inputs must name exactly {sorted(INPUT_NAMES)}")
    for name, entry in inputs.items():
        if entry is not None:
            _sha256_entry(entry, f"inputs.{name}")
    outputs = provenance["outputs"]
    allowed = set(OUTPUT_NAMES) | set(RETAINED_INPUTS.values())
    if not isinstance(outputs, dict) or not set(OUTPUT_NAMES) <= set(outputs) <= allowed:
        raise ValueError(f"provenance outputs must name {list(OUTPUT_NAMES)} and optionally "
                         f"{sorted(RETAINED_INPUTS.values())}")
    return {name: _sha256_entry(entry, f"outputs.{name}") for name, entry in outputs.items()}


def _strict_jsonl(text: str, what: str) -> list[dict]:
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        row = loads_strict(line)
        if not isinstance(row, dict):
            raise ValueError(f"{what} line {number}: expected an object")
        rows.append(row)
    return rows


def _cases_from_rows(rows: list[dict], questions: tuple) -> list[Case]:
    """Rebuild the scored cases: ids and expected answers come from cases.jsonl (states are not retained)."""
    by_name = {question.name: question for question in questions}
    cases, seen = [], set()
    for number, row in enumerate(rows, 1):
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError(f"cases.jsonl row {number}: id must be a unique non-empty string")
        seen.add(case_id)
        results = row.get("questions", {})
        if not isinstance(results, dict):
            raise ValueError(f"cases.jsonl row {number}: questions must be an object")
        labels = {}
        for name, result in results.items():
            if name not in by_name or not isinstance(result, dict) or "expected" not in result:
                raise ValueError(f"cases.jsonl row {number}: invalid result for {name!r}")
            labels[name] = _expected(by_name[name], result["expected"], f"cases.jsonl row {number} {name!r}")
        cases.append(Case(case_id, None, labels))
    if not cases:
        raise ValueError("cases.jsonl has no cases")
    return cases


FLOAT_TOLERANCE = 1e-9
FLOAT_FLOOR = 1e-12  # absolute bound, used only where the expected value is exactly 0


def _exact(left: Any, right: Any) -> bool:
    dump = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)  # noqa: E731
    return dump(left) == dump(right)


def _close(expected: Any, recorded: Any, exact_keys: frozenset = frozenset()) -> bool:
    """Structural equality where derived floats match within a relative 1e-9.

    Metrics use math.log and NormalDist.inv_cdf, whose last digits differ between platform math
    libraries, so a recomputed float is compared with a tolerance. Strings, integers, booleans,
    null, structure and the members named in `exact_keys` (inputs such as bounds) compare exactly.
    """
    if isinstance(expected, dict):
        return (isinstance(recorded, dict) and set(expected) == set(recorded)
                and all(_exact(expected[key], recorded[key]) if key in exact_keys
                        else _close(expected[key], recorded[key], exact_keys) for key in expected))
    if isinstance(expected, list):
        return (isinstance(recorded, list) and len(expected) == len(recorded)
                and all(_close(left, right, exact_keys) for left, right in zip(expected, recorded)))
    if isinstance(expected, float) and type(recorded) in (int, float):
        if expected == 0:
            return abs(recorded) <= FLOAT_FLOOR
        return abs(recorded - expected) <= FLOAT_TOLERANCE * abs(expected)
    return type(expected) is type(recorded) and expected == recorded


def _input_bytes(name: str, contents: dict[str, bytes], recorded: dict | None, supplied: Path | None,
                 mismatches: list[str]) -> bytes | None:
    """The bytes of an input the run read, from the retained copy or a supplied file; None when absent.

    Both are checked against the input hash in provenance.json. Only questions and requirements are
    retained; cases (with states) and supplied responses are not needed to re-score.
    """
    candidates = [(RETAINED_INPUTS[name], contents.get(RETAINED_INPUTS[name]))]
    if supplied is not None:
        candidates.append((str(supplied), supplied.read_bytes()))
    data = None
    for source, blob in candidates:
        if blob is None:
            continue
        if recorded is None or hashlib.sha256(blob).hexdigest() != recorded["sha256"]:
            mismatches.append(f"{source} (differs from the {name} input hashed in provenance.json)")
        data = blob if data is None else data
    return data


def verify_evaluation_dir(directory: Path, questions_file: Path | None = None,
                          requirements_file: Path | None = None) -> list[str]:
    """Return mismatched files and fields; raise ValueError/OSError for unreadable or invalid records."""
    directory = Path(directory)
    provenance = loads_strict((directory / "provenance.json").read_text(encoding="utf-8"))
    hashes = _check_provenance(provenance)
    mismatches: list[str] = []
    contents: dict[str, bytes] = {}
    for name, expected in hashes.items():
        try:
            contents[name] = (directory / name).read_bytes()
        except FileNotFoundError:
            mismatches.append(f"{name} (missing)")
            continue
        if hashlib.sha256(contents[name]).hexdigest() != expected:
            mismatches.append(name)
    inputs = provenance["inputs"]
    question_bytes = _input_bytes("questions", contents, inputs["questions"], questions_file, mismatches)
    requirement_bytes = _input_bytes("requirements", contents, inputs["requirements"], requirements_file, mismatches)
    if mismatches:
        return mismatches  # files that fail their hash cannot be trusted for re-scoring
    if question_bytes is None:
        raise ValueError("cannot re-score: no retained questions.json (written by newer runs); "
                         "pass --questions with the original question file")
    if requirement_bytes is None and inputs["requirements"] is not None:
        raise ValueError("cannot re-score: no retained requirements.json (written by newer runs); "
                         "pass --requirements with the original requirement file")
    requirements = {} if requirement_bytes is None else loads_strict(requirement_bytes.decode("utf-8"))

    questions = check_question_set(questions_from_spec(loads_strict(question_bytes.decode("utf-8"))))
    report = loads_strict(contents["evaluation.json"].decode("utf-8"))
    if not isinstance(report, dict) or not _is_int(report.get("schema_version"), 2):
        raise ValueError("unsupported evaluation schema_version; expected 2")
    _check_fields(report, EVALUATION_FIELDS, "evaluation.json")
    _check_producer(report["produced_by"], "evaluation.json")
    if (report["produced_by"]["version"] != report["jevdecision_version"] or report["backend"] not in BACKENDS
            or report["source"] not in ("live", "replay") or not isinstance(report["model"], str)
            or not isinstance(report["errors"], list)):
        raise ValueError("evaluation.json: invalid producer, backend, source, model or errors")
    recorded_errors = {}
    for error in report["errors"]:
        if not isinstance(error, dict) or set(error) != {"id", "error"} or not isinstance(error["id"], str):
            raise ValueError("evaluation.json: invalid errors entry")
        recorded_errors[error["id"]] = error["error"]

    case_rows = _strict_jsonl(contents["cases.jsonl"].decode("utf-8"), "cases.jsonl")
    cases = _cases_from_rows(case_rows, questions)
    responses: dict[str, Any] = {}
    for number, row in enumerate(_strict_jsonl(contents["responses.jsonl"].decode("utf-8"), "responses.jsonl"), 1):
        if not isinstance(row.get("id"), str) or "response" not in row or row["id"] in responses:
            raise ValueError(f"responses.jsonl row {number}: needs a unique string id and a response")
        responses[row["id"]] = row["response"]
    if set(responses) - {case.id for case in cases}:
        return ["responses.jsonl (responses for cases not in cases.jsonl)"]

    backend = create_backend(report["backend"], api_key="offline", env={})
    answers, raw, errors = replay(backend, questions, cases, responses)
    if report["source"] == "live":  # a failed request leaves no response to re-derive its message from
        errors = [{**error, "error": recorded_errors.get(error["id"], error["error"])}
                  if error["error"] == "no recorded response" else error for error in errors]
    models = sorted({str(r.get("model")) for r in raw.values() if isinstance(r, dict) and r.get("model")})
    expected = {"schema_version": 2, "produced_by": report["produced_by"],
                "jevdecision_version": report["jevdecision_version"], "backend": report["backend"],
                "model": ", ".join(models) or report["model"], "source": report["source"],
                **evaluate(questions, cases, answers, errors, requirements)}
    mismatches += [f"evaluation.json:{key}" for key, value in expected.items()
                   if not _close(value, report[key], frozenset({"limit"}))]
    if not _exact(case_results(questions, cases, answers, errors), case_rows):
        mismatches.append("cases.jsonl")
    if provenance["response_mode"] != report["source"]:
        mismatches.append("provenance.json:response_mode")
    return mismatches


# Command line --------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jev-decision-verify", description=__doc__.split("\n")[0])
    parser.add_argument("answers", nargs="*", type=Path, metavar="ANSWER_JSON",
                        help="schema 2 answer records written by jev-decision")
    parser.add_argument("--evaluation", action="append", type=Path, default=[], metavar="DIR",
                        help="evaluation output directory written by jev-decision-eval (repeatable)")
    parser.add_argument("--questions", type=Path, metavar="FILE",
                        help="original question file, for evaluation directories without a retained questions.json")
    parser.add_argument("--requirements", type=Path, metavar="FILE",
                        help="original requirement file, for directories without a retained requirements.json")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.answers and not args.evaluation:
        parser.error("give at least one ANSWER_JSON or --evaluation DIR")
    if (args.questions is not None or args.requirements is not None) and len(args.evaluation) != 1:
        parser.error("--questions and --requirements need exactly one --evaluation DIR")

    result = 0
    checks = [(path, lambda path=path: verify_answer_record(
        loads_strict(path.read_text(encoding="utf-8")))) for path in args.answers]
    checks += [(path, lambda path=path: verify_evaluation_dir(path, args.questions, args.requirements)) for path in args.evaluation]
    for path, check in checks:
        try:
            mismatches = check()
        except (OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
            print(f"{path}: cannot verify: {exc}", file=sys.stderr)
            result = max(result, 2)
            continue
        if mismatches:
            print(f"{path}: mismatch: {', '.join(mismatches)}")
            result = max(result, 1)
        else:
            print(f"{path}: verified")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
