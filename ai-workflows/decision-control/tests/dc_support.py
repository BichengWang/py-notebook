"""Shared test helpers: deliberate checksum recomputation and shipped-schema loading.

jsonschema is a dev/CI-only dependency, absent at runtime; tests that need it skip.
"""
import hashlib
from importlib import resources
import json

from decisioncontrol.jcs import canonicalize

try:
    import jsonschema
except ImportError:  # tests that need it skip cleanly
    jsonschema = None

def python_json_v1(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_for(value, schema_version, jcs_from):
    blob = canonicalize(value) if schema_version >= jcs_from else python_json_v1(value)
    return hashlib.sha256(blob).hexdigest()


def rehash_record(envelope):
    """Recompute the checksum under the rules of the record's own schema version."""
    record = envelope["record"]
    envelope["sha256"] = sha256_for(record, record["schema_version"], 4)
    return envelope


def as_schema4(record):
    """Return a schema 4 copy of a schema 5 record: no external-policy members."""
    legacy = json.loads(json.dumps(record))
    legacy["schema_version"] = 4
    legacy.pop("external_policy", None)
    legacy.pop("external_policy_sha256", None)
    return legacy


def as_schema3(record):
    """Return a schema 3 copy of a schema 4 or 5 record, with python-json-v1 policy digest."""
    legacy = as_schema4(record)
    legacy["schema_version"] = 3
    legacy["policy_sha256"] = hashlib.sha256(python_json_v1(legacy["policy"])).hexdigest()
    return legacy


def rehash_report(envelope):
    report = envelope["report"]
    envelope["sha256"] = sha256_for(report, report["schema_version"], 2)
    return envelope


RECORD_VERSIONS = (1, 2, 3, 4, 5)
EVALUATION_VERSIONS = (1, 2)
ID_PREFIX = "https://github.com/BichengWang/ai-decision-system/schema/decisioncontrol/"


def schema_names():
    return ([f"record.v{n}.json" for n in RECORD_VERSIONS]
            + [f"evaluation.v{n}.json" for n in EVALUATION_VERSIONS])


def load_schema(name):
    return json.loads((resources.files("decisioncontrol") / "schema" / name).read_text(encoding="utf-8"))


def validator(name):
    schema = load_schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)
