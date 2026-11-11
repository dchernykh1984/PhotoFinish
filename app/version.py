"""This program's version: pyproject.toml's, which release-please bumps -- the
repository's in development, the copy a frozen build carries beside its code.
A window and a recorder of one install read the same file, so they agree unless an
update came between their starts (specs/007).
"""

from __future__ import annotations

import functools
import sys
import tomllib
from pathlib import Path


@functools.cache
def version() -> str:
    """The version; "" when no pyproject.toml can be read, as in older builds."""
    bundled = getattr(sys, "_MEIPASS", None)  # a frozen build's own folder
    root = Path(bundled) if bundled else Path(__file__).resolve().parent.parent
    try:
        with (root / "pyproject.toml").open("rb") as f:
            return str(tomllib.load(f)["project"]["version"])
    except OSError, KeyError, TypeError, tomllib.TOMLDecodeError:
        return ""
