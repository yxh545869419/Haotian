"""Filesystem traversal helpers that reject symlinked or aliased paths."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import os
import stat


def is_alias_path(path: Path) -> bool:
    if path.is_symlink():
        return True

    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            return bool(is_junction())
        except OSError:
            return False

    if os.name == "nt":
        try:
            return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except OSError:
            return False

    return False


def iter_safe_files(root: Path) -> Iterator[Path]:
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if not is_alias_path(current_path / name)]
        for name in files:
            candidate = current_path / name
            if is_alias_path(candidate):
                continue
            if candidate.is_file():
                yield candidate
