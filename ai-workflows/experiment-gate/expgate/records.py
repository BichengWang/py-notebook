"""Canonical encoding for input-summary change detection."""
import hashlib
import json


def canonical_json(value: object) -> str:
    """Encode JSON content deterministically, preserving JSON value types."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def input_digest(summary: dict) -> str:
    """SHA-256 of canonical UTF-8 JSON; this detects changes, not forgery."""
    return hashlib.sha256(canonical_json(summary).encode("utf-8")).hexdigest()
