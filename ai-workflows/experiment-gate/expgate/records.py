"""Canonical encodings for input-summary change detection.

Schema 2 records use ``python-json-v1``: Python's ``json.dumps`` with sorted keys, compact
separators and ``ensure_ascii=False``. Schema 3 records use RFC 8785 (JCS, see :mod:`expgate.jcs`),
which other languages can reproduce byte for byte.
"""
import hashlib
import json

from .jcs import canonicalize

SCHEMA_VERSION = 3
SUPPORTED_SCHEMAS = (2, 3)

# Schema 2 replays with the 0.1.0 tail formulas (2 * (1 - cdf), inv_cdf(1 - alpha)); schema 3 uses the
# accurate ones (erfc, -inv_cdf(alpha)). This is the only place the two differ.
EXACT_TAIL = {2: False, 3: True}

# Schema 3 replay: derived floats agree within this relative tolerance (see compare_replay in verify.py).
REPLAY_RELATIVE_TOLERANCE = 1e-9
REPLAY_ZERO_FLOOR = 1e-12


def canonical_json(value: object) -> str:
    """Encode JSON content as ``python-json-v1`` (schema 2), preserving JSON value types."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(value: object, schema_version: int = SCHEMA_VERSION) -> bytes:
    """Canonical UTF-8 bytes under the rules of ``schema_version``; ValueError if not encodable."""
    if schema_version == 2:
        return canonical_json(value).encode("utf-8")
    if schema_version == 3:
        return canonicalize(value)
    raise ValueError(f"no canonical encoding for schema_version {schema_version!r}")


def input_digest(summary: dict, schema_version: int = SCHEMA_VERSION) -> str:
    """SHA-256 of the canonical encoding; this detects changes, not forgery."""
    return hashlib.sha256(canonical_bytes(summary, schema_version)).hexdigest()
