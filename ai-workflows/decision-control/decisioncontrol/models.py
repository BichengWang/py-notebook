"""Versioned, provider-neutral inputs for a bounded ticket action."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import math


class DecisionError(ValueError):
    """Invalid input or evidence; no action is authorized."""


class StateError(DecisionError):
    """The requested lifecycle transition is not permitted."""


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REVIEW = "REVIEW"
    ABSTAIN = "ABSTAIN"


class Status(str, Enum):
    READY = "READY"
    PENDING_REVIEW = "PENDING_REVIEW"
    DENIED = "DENIED"
    ABSTAINED = "ABSTAINED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXECUTED = "EXECUTED"
    STALE = "STALE"


def _fields(value, required, optional=()):
    if not isinstance(value, Mapping):
        raise DecisionError("expected a JSON object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise DecisionError(f"invalid fields: missing {sorted(missing)}, unexpected {sorted(extra, key=str)}")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise DecisionError(f"{name} must be a nonempty string without surrounding whitespace")
    return value


def _probability(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionError(f"{name} must be a finite probability in [0, 1]")
    if not 0 <= value <= 1 or not math.isfinite(value):
        raise DecisionError(f"{name} must be a finite probability in [0, 1]")
    return float(value)


def _names(value, name, allow_empty=False):
    if not isinstance(value, (list, tuple)):
        raise DecisionError(f"{name} must be a list or tuple of names")
    names = tuple(_text(item, name) for item in value)
    if (not names and not allow_empty) or len(set(names)) != len(names):
        raise DecisionError(f"{name} must contain {'unique' if allow_empty else 'one or more unique'} names")
    return names


@dataclass(frozen=True)
class Recommendation:
    action: str
    ticket_id: str
    destination: str
    probability: float | None
    model: str
    question_version: str
    refused: bool = False

    def __post_init__(self):
        for name in ("action", "ticket_id", "destination", "model", "question_version"):
            _text(getattr(self, name), name)
        if self.probability is not None:
            object.__setattr__(self, "probability", _probability(self.probability, "probability"))
        if not isinstance(self.refused, bool):
            raise DecisionError("refused must be a boolean")

    def to_dict(self):
        return {"action": self.action, "ticket_id": self.ticket_id,
                "destination": self.destination, "probability": self.probability,
                "model": self.model, "question_version": self.question_version,
                "refused": self.refused}

    @classmethod
    def from_dict(cls, value):
        raw = _fields(value, {"action", "ticket_id", "destination", "model", "question_version"},
                      {"probability", "refused"})
        return cls(action=raw["action"], ticket_id=raw["ticket_id"], destination=raw["destination"],
                   probability=raw.get("probability"), model=raw["model"],
                   question_version=raw["question_version"], refused=raw.get("refused", False))


@dataclass(frozen=True)
class Ticket:
    id: str
    department: str
    revision: int = 0

    def __post_init__(self):
        _text(self.id, "ticket id")
        _text(self.department, "department")
        if type(self.revision) is not int or self.revision < 0:
            raise DecisionError("revision must be a nonnegative integer")

    def to_dict(self):
        return {"id": self.id, "department": self.department, "revision": self.revision}

    @classmethod
    def from_dict(cls, value):
        raw = _fields(value, {"id", "department", "revision"})
        return cls(**raw)


@dataclass(frozen=True)
class RoutingPolicy:
    version: str
    allowed_destinations: tuple[str, ...]
    review_destinations: tuple[str, ...]
    reviewers: tuple[str, ...]
    min_probability: float = 0.8

    def __post_init__(self):
        _text(self.version, "policy version")
        object.__setattr__(self, "allowed_destinations", _names(self.allowed_destinations, "allowed_destinations"))
        object.__setattr__(self, "review_destinations", _names(self.review_destinations, "review_destinations", True))
        object.__setattr__(self, "reviewers", _names(self.reviewers, "reviewers"))
        object.__setattr__(self, "min_probability", _probability(self.min_probability, "min_probability"))
        if not set(self.review_destinations) <= set(self.allowed_destinations):
            raise DecisionError("review_destinations must be a subset of allowed_destinations")

    def to_dict(self):
        return {"version": self.version, "allowed_destinations": list(self.allowed_destinations),
                "review_destinations": list(self.review_destinations), "reviewers": list(self.reviewers),
                "min_probability": self.min_probability}

    @classmethod
    def from_dict(cls, value):
        raw = _fields(value, {"version", "allowed_destinations", "review_destinations", "reviewers"},
                      {"min_probability"})
        return cls(**raw)


@dataclass(frozen=True)
class Evaluation:
    verdict: Verdict
    reasons: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.verdict, Verdict):
            raise DecisionError("verdict must be a Verdict")
        object.__setattr__(self, "reasons", _names(self.reasons, "reasons"))

    def to_dict(self):
        return {"verdict": self.verdict.value, "reasons": list(self.reasons)}

    @classmethod
    def from_dict(cls, value):
        raw = _fields(value, {"verdict", "reasons"})
        try:
            verdict = Verdict(raw["verdict"])
        except (ValueError, TypeError) as error:
            raise DecisionError("unknown verdict") from error
        return cls(verdict, raw["reasons"])
