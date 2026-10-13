"""Publish complete artifacts from staging directories on the same filesystem."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from typing import Iterator

from .models import DecisionError


def _check_target(target: Path, directory: bool) -> None:
    if target.is_symlink() or (target.exists() and (
            not directory or not target.is_dir() or any(target.iterdir()))):
        raise DecisionError("output must be a new file or a new or empty directory")


@contextmanager
def staged_output(out: str | Path, *, directory: bool = True) -> Iterator[Path]:
    target = Path(out)
    _check_target(target, directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as temporary:
        staging = Path(temporary) / "output"
        if directory:
            staging.mkdir()
        yield staging
        _check_target(target, directory)
        os.replace(staging, target)
