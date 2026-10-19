"""Answer record schema 2: typed answers plus the evidence needed to re-check them.

A schema 1 answer record holds only the typed answers, so nothing in it can be
re-derived. Schema 2 also embeds the question definitions (Jev's question map,
normalized) and the raw provider response, and carries `record_sha256`: the
lowercase hex SHA-256 of the RFC 8785 (JCS) canonical form of the whole record
without the `record_sha256` member. `jev-decision-verify` re-parses the embedded
response with the embedded questions and compares the result.

The state text is not embedded; it may be sensitive and parsing does not need it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from typing import Any

from . import __version__
from .answers import Decision
from .jcs import canonicalize
from .questions import Choice, Question, Score

ANSWER_SCHEMA_VERSION = 2
DIGEST_FIELD = "record_sha256"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def question_spec(questions: Iterable[Question]) -> dict[str, dict[str, Any]]:
    """Jev's question map {name: {type, instructions[, criteria]}} for `questions`."""
    spec: dict[str, dict[str, Any]] = {}
    for question in questions:
        entry: dict[str, Any] = {"type": question.type, "instructions": question.instructions}
        if isinstance(question, Choice):
            entry["criteria"] = dict(question.options)
        elif isinstance(question, Score):
            entry["criteria"] = list(question.levels)
        spec[question.name] = entry
    return spec


def record_digest(record: dict[str, Any]) -> str:
    """SHA-256 of the canonical record without its own digest member."""
    body = {key: value for key, value in record.items() if key != DIGEST_FIELD}
    return hashlib.sha256(canonicalize(body)).hexdigest()


def answer_record(decision: Decision, questions: Iterable[Question]) -> dict[str, Any]:
    """Schema 2 record for a decision; raises ValueError when the raw response cannot be canonicalized."""
    record: dict[str, Any] = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "produced_by": {"name": "jevdecision", "version": __version__},
        "backend": decision.backend,
        "model": decision.model,
        "id": decision.id,
        "usage": dict(decision.usage),
        "answers": {name: answer.to_dict() for name, answer in decision.answers.items()},
        "questions": question_spec(questions),
        "response": decision.raw,
    }
    record[DIGEST_FIELD] = record_digest(record)
    return record


def dumps_record(record: dict[str, Any]) -> str:
    """The record as RFC 8785 canonical JSON text."""
    return canonicalize(record).decode("utf-8")


# Strict parsing ------------------------------------------------------------

def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def _constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name}")


def _float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"non-finite number {text}")
    return value


def loads_strict(text: str) -> Any:
    """Parse JSON, rejecting duplicate object keys and non-finite numbers."""
    return json.loads(text, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float)
