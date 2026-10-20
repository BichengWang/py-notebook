"""Versioned, provider-neutral inputs for a bounded ticket action."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import math

from .actions import CURRENT_SCHEMA, LEGACY_ACTIONS_SCHEMA, actions_for


class DecisionError(ValueError):
    """Invalid input or evidence; no action is authorized."""


class StateError(DecisionError):
    """The requested lifecycle transition is not permitted."""


class RecordMismatch(DecisionError):
    """A checksum, recomputed decision or re-evaluated policy disagrees with recorded evidence."""


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


def _target_field(action, schema):
    """Recommendation member that carries the requested value for ``action`` under ``schema``."""
    registered = actions_for(schema).get(action) if isinstance(action, str) else None
    return registered.target_field if registered else "destination"


@dataclass(frozen=True)
class Recommendation:
    """A proposed action. ``destination`` carries the target of ``reassign_ticket`` (and of any
    unregistered action, which policy denies); ``priority`` carries the target of
    ``set_ticket_priority``. Exactly one of the two is set; the registry entry of the action
    says which one it reads."""

    action: str
    ticket_id: str
    destination: str | None
    probability: float | None
    model: str
    question_version: str
    refused: bool = False
    priority: str | None = None

    def __post_init__(self):
        for name in ("action", "ticket_id", "model", "question_version"):
            _text(getattr(self, name), name)
        if (self.destination is None) == (self.priority is None):
            raise DecisionError("a recommendation sets exactly one of destination and priority")
        _text(self.destination if self.priority is None else self.priority,
              "destination" if self.priority is None else "priority")
        if self.probability is not None:
            object.__setattr__(self, "probability", _probability(self.probability, "probability"))
        if not isinstance(self.refused, bool):
            raise DecisionError("refused must be a boolean")

    @property
    def target(self):
        """The requested value, whichever member carries it."""
        return self.priority if self.destination is None else self.destination

    def to_dict(self):
        member = "priority" if self.destination is None else "destination"
        return {"action": self.action, "ticket_id": self.ticket_id, member: self.target,
                "probability": self.probability, "model": self.model,
                "question_version": self.question_version, "refused": self.refused}

    @classmethod
    def from_dict(cls, value, schema=CURRENT_SCHEMA):
        action = value.get("action") if isinstance(value, Mapping) else None
        target = _target_field(action, schema)
        raw = _fields(value, {"action", "ticket_id", "model", "question_version", target},
                      {"probability", "refused"})
        return cls(action=raw["action"], ticket_id=raw["ticket_id"], destination=raw.get("destination"),
                   probability=raw.get("probability"), model=raw["model"],
                   question_version=raw["question_version"], refused=raw.get("refused", False),
                   priority=raw.get("priority"))


@dataclass(frozen=True)
class Ticket:
    id: str
    department: str
    revision: int = 0
    priority: str | None = None

    def __post_init__(self):
        _text(self.id, "ticket id")
        _text(self.department, "department")
        if type(self.revision) is not int or self.revision < 0:
            raise DecisionError("revision must be a nonnegative integer")
        if self.priority is not None:
            _text(self.priority, "priority")

    def to_dict(self):
        value = {"id": self.id, "department": self.department, "revision": self.revision}
        if self.priority is not None:
            value["priority"] = self.priority
        return value

    @classmethod
    def from_dict(cls, value, schema=CURRENT_SCHEMA):
        optional = {"priority"} if schema > LEGACY_ACTIONS_SCHEMA else ()
        raw = _fields(value, {"id", "department", "revision"}, optional)
        return cls(**raw)


@dataclass(frozen=True)
class RoutingPolicy:
    """Frozen rules for every registered action: allowlists and review lists per action type.

    ``allowed_destinations``/``review_destinations`` govern ``reassign_ticket``;
    ``allowed_priorities``/``review_priorities`` govern ``set_ticket_priority``. A value that
    is not listed is not permitted, so an empty priority allowlist denies every priority change.
    """

    version: str
    allowed_destinations: tuple[str, ...]
    review_destinations: tuple[str, ...]
    reviewers: tuple[str, ...]
    min_probability: float = 0.8
    allowed_priorities: tuple[str, ...] = ()
    review_priorities: tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.version, "policy version")
        object.__setattr__(self, "allowed_destinations", _names(self.allowed_destinations, "allowed_destinations"))
        object.__setattr__(self, "review_destinations", _names(self.review_destinations, "review_destinations", True))
        object.__setattr__(self, "reviewers", _names(self.reviewers, "reviewers"))
        object.__setattr__(self, "min_probability", _probability(self.min_probability, "min_probability"))
        object.__setattr__(self, "allowed_priorities", _names(self.allowed_priorities, "allowed_priorities", True))
        object.__setattr__(self, "review_priorities", _names(self.review_priorities, "review_priorities", True))
        if not set(self.review_destinations) <= set(self.allowed_destinations):
            raise DecisionError("review_destinations must be a subset of allowed_destinations")
        if not set(self.review_priorities) <= set(self.allowed_priorities):
            raise DecisionError("review_priorities must be a subset of allowed_priorities")

    def to_dict(self):
        value = {"version": self.version, "allowed_destinations": list(self.allowed_destinations),
                 "review_destinations": list(self.review_destinations), "reviewers": list(self.reviewers),
                 "min_probability": self.min_probability}
        if self.allowed_priorities:
            value["allowed_priorities"] = list(self.allowed_priorities)
            value["review_priorities"] = list(self.review_priorities)
        return value

    @classmethod
    def from_dict(cls, value, schema=CURRENT_SCHEMA):
        optional = {"min_probability"}
        if schema > LEGACY_ACTIONS_SCHEMA:
            optional |= {"allowed_priorities", "review_priorities"}
        raw = _fields(value, {"version", "allowed_destinations", "review_destinations", "reviewers"}, optional)
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
