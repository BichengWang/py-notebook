"""in-toto Statement v1 in a DSSE envelope, signed with HMAC-SHA256 (standard library).

The statement's subject is the SHA-256 of the record file's exact bytes, the same
subject `cosign attest-blob` computes, so a record can carry an HMAC envelope, a
Sigstore bundle, or both. HMAC proves possession of a shared secret key, not a
public identity. Sigstore verification is delegated to an external `cosign`.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

from .jcs import canonicalize

PAYLOAD_TYPE = "application/vnd.in-toto+json"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
KEY_BYTES = 32


class SignatureError(Exception):
    """The record is unsigned, the signature is wrong, or it signs other content."""


class KeyFileError(ValueError):
    """The key file is missing or malformed (an input error, exit 2)."""


def generate_key(path: Path) -> str:
    """Write a new random key as hex (mode 0600) and return its key id."""
    key = secrets.token_bytes(KEY_BYTES)
    path = Path(path)
    with open(path, "x", encoding="ascii", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        stream.write(key.hex() + "\n")
    return key_id(key)


def load_key(path: Path) -> bytes:
    try:
        text = Path(path).read_text(encoding="ascii").strip()
        key = bytes.fromhex(text)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise KeyFileError(f"cannot read HMAC key from {path}: {error}") from error
    if len(key) < KEY_BYTES:
        raise KeyFileError(f"HMAC key in {path} must be at least {KEY_BYTES} bytes of hex")
    return key


def key_id(key: bytes) -> str:
    return "hmac-sha256:" + hashlib.sha256(key).hexdigest()[:16]


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE v1 pre-authentication encoding."""
    kind = payload_type.encode("utf-8")
    return b"DSSEv1 %d %s %d %s" % (len(kind), kind, len(payload), payload)


def statement(record_bytes: bytes, name: str, predicate_type: str, predicate: dict) -> dict:
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": name, "digest": {"sha256": hashlib.sha256(record_bytes).hexdigest()}}],
        "predicateType": predicate_type,
        "predicate": predicate,
    }


def sign(record_bytes: bytes, name: str, predicate_type: str, predicate: dict, key: bytes) -> dict:
    """Return a DSSE envelope over the record's in-toto statement."""
    payload = canonicalize(statement(record_bytes, name, predicate_type, predicate))
    signature = hmac.new(key, pae(PAYLOAD_TYPE, payload), hashlib.sha256).digest()
    return {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [{"keyid": key_id(key), "sig": base64.b64encode(signature).decode("ascii")}],
    }


def verify(record_bytes: bytes, envelope: object, predicate_types: set[str], key: bytes) -> dict:
    """Check the envelope signs these exact record bytes; return the statement."""
    if not isinstance(envelope, dict) or envelope.get("payloadType") != PAYLOAD_TYPE:
        raise SignatureError("not an in-toto DSSE envelope")
    try:
        payload = base64.b64decode(envelope["payload"], validate=True)
        signatures = envelope["signatures"]
    except (KeyError, TypeError, ValueError) as error:
        raise SignatureError(f"malformed DSSE envelope: {error}") from error
    wanted = key_id(key)
    expected = hmac.new(key, pae(PAYLOAD_TYPE, payload), hashlib.sha256).digest()
    matched = False
    for entry in signatures if isinstance(signatures, list) else []:
        if not isinstance(entry, dict) or entry.get("keyid") != wanted:
            continue
        sig = entry.get("sig")
        if not isinstance(sig, str):
            continue
        try:
            given = base64.b64decode(sig, validate=True)
        except ValueError:
            continue
        if hmac.compare_digest(given, expected):
            matched = True
            break
    if not matched:
        raise SignatureError(f"no valid signature for key {wanted}")
    try:
        body = json.loads(payload)
        subjects = body["subject"]
        kind = body["predicateType"]
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        raise SignatureError(f"signed payload is not an in-toto statement: {error}") from error
    if body.get("_type") != STATEMENT_TYPE:
        raise SignatureError("signed payload is not an in-toto Statement v1")
    if not isinstance(kind, str) or kind not in predicate_types:
        raise SignatureError(f"predicate type {kind!r} does not match this record type")
    if not isinstance(subjects, list):
        raise SignatureError("signed statement subject is not a list")
    digest = hashlib.sha256(record_bytes).hexdigest()
    if not any(_names_digest(subject, digest) for subject in subjects):
        raise SignatureError("signature covers different record bytes")
    return body


def _names_digest(subject: object, digest: str) -> bool:
    """True when an in-toto subject carries this lowercase hex SHA-256."""
    if not isinstance(subject, dict) or not isinstance(subject.get("digest"), dict):
        return False
    value = subject["digest"].get("sha256")
    return (isinstance(value, str) and len(value) == len(digest)
            and all(char in "0123456789abcdef" for char in value)
            and hmac.compare_digest(value, digest))


def verify_sigstore(record: Path, bundle: Path, predicate_type: str, identity: str, issuer: str) -> None:
    """Delegate Sigstore verification to `cosign verify-blob-attestation`."""
    cosign = shutil.which("cosign")
    if cosign is None:
        raise KeyFileError("cosign is not installed; Sigstore verification needs it on PATH")
    result = subprocess.run(
        [cosign, "verify-blob-attestation", "--bundle", str(bundle), "--type", predicate_type,
         "--certificate-identity", identity, "--certificate-oidc-issuer", issuer, str(record)],
        capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SignatureError(f"cosign rejected the attestation: {result.stderr.strip()}")
