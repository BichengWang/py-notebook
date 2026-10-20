"""expgate: ship / hold / rollback gates for online experiments of decision models."""

__version__ = "0.2.0"

from .decision import evaluate


def verify_record(record: dict) -> list[str]:
    """Return mismatch fields for a schema-2 or schema-3 record; invalid records raise ValueError."""
    from .verify import verify_record as verify
    return verify(record)


__all__ = ["evaluate", "verify_record", "__version__"]
