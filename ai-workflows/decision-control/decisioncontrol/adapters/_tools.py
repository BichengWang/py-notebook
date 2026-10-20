"""Run optional external policy tools with a minimal environment and a timeout."""

import shutil
import subprocess

from ..models import DecisionError


class ToolFailure(DecisionError):
    """The tool ran and reported failure (for example it rejected the frozen policy)."""


def find(name):
    """Absolute path of ``name`` on PATH, or ``None`` when it is not installed."""
    return shutil.which(name)


def run(argv, *, cwd, stdin=None, timeout=60):
    """Run ``argv``; spawn errors and timeouts are DecisionError, a nonzero exit is returned."""
    try:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, cwd=cwd,
                              env={"PATH": "", "LC_ALL": "C", "HOME": str(cwd)}, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise DecisionError(f"could not run {argv[0]}: {error}") from error


def first_line(text, limit=300):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:limit]
    return "no output"
