"""Offline adapters that freeze an external policy decision into a decision record.

The adapters read recorded decisions and local files. They open no network
connection and run no service; ``opa`` and ``cedar`` are optional subprocesses
used only to freeze a Cedar decision and to re-evaluate a frozen decision on replay.
"""

from collections.abc import Mapping

from ..models import DecisionError
from . import cedar, opa

ENGINES = {opa.NAME: opa, cedar.NAME: cedar}


def engine_for(frozen):
    """The adapter module named by the ``engine`` member of a frozen external decision."""
    name = frozen.get("engine") if isinstance(frozen, Mapping) else None
    if not isinstance(name, str) or name not in ENGINES:
        raise DecisionError(f"external policy engine must be one of {sorted(ENGINES)}")
    return ENGINES[name]
