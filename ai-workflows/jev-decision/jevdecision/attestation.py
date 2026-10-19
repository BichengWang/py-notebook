"""Sign answer records and evaluation provenance, and require those signatures when verifying.

The signed subject is the SHA-256 of the exact bytes of the signed file, so an edit that re-hashes
the embedded digest still fails `--require-signature`. An answer record is signed as a whole; for an
evaluation directory the signed file is `provenance.json`, which already pins every other file by
hash. HMAC proves possession of a shared secret, not an identity; Sigstore verification is
delegated to an external `cosign`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import signing

PREDICATE_BASE = "https://github.com/BichengWang/ai-decision-system/predicate/jevdecision/"
SCHEMA_BASE = "https://github.com/BichengWang/ai-decision-system/schema/jevdecision/"
SUPPORTED = {"answer": (1, 2), "provenance": (2,)}
ENVELOPE_SUFFIX = ".dsse.json"
BUNDLE_SUFFIX = ".sigstore.json"
PROVENANCE = "provenance.json"


def predicate_type(kind: str, version: int) -> str:
    return f"{PREDICATE_BASE}{kind}/v{version}"


def predicate(kind: str, version: int) -> dict[str, str]:
    return {"schema": f"{SCHEMA_BASE}{kind}.v{version}.json"}


def answer_version(record: Any) -> int:
    """Schema version of an answer record; anything unsupported is an input error (ValueError)."""
    version = record.get("schema_version") if isinstance(record, dict) else None
    if type(version) is not int or version not in SUPPORTED["answer"]:
        raise ValueError("unsupported answer record schema_version; expected 1 or 2")
    return version


def envelope_path(record: Path) -> Path:
    return Path(str(record) + ENVELOPE_SUFFIX)


def sign_bytes(data: bytes, name: str, kind: str, version: int, key: bytes) -> dict:
    """The DSSE envelope for the exact bytes of a record file."""
    return signing.sign(data, name, predicate_type(kind, version), predicate(kind, version), key)


def render_envelope(envelope: dict) -> str:
    return json.dumps(envelope, indent=2) + "\n"


def require_signature(record: Path, data: bytes, kind: str, version: int, options: Any) -> None:
    """Raise SignatureError (exit 1) or KeyFileError (exit 2) unless the file is signed as required.

    `options` carries key, signature, sigstore_bundle, certificate_identity and
    certificate_oidc_issuer; exactly one of key or sigstore_bundle is set.
    """
    expected = predicate_type(kind, version)
    if options.key is not None:
        key = signing.load_key(options.key)
        path = Path(options.signature) if options.signature else envelope_path(record)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise signing.SignatureError(f"unsigned: no signature envelope at {path}") from error
        except (OSError, UnicodeError) as error:
            raise signing.SignatureError(f"cannot read signature envelope {path}: {error}") from error
        try:
            envelope = json.loads(text)
        except ValueError as error:
            raise signing.SignatureError(f"malformed DSSE envelope: {error}") from error
        signing.verify(data, envelope, {expected}, key)
        return
    bundle = Path(options.sigstore_bundle)
    if not bundle.is_file():
        raise signing.SignatureError(f"unsigned: no Sigstore bundle at {bundle}")
    signing.verify_sigstore(record, bundle, expected, options.certificate_identity,
                            options.certificate_oidc_issuer)
