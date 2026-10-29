"""Files other processes read while this one writes them, and the other way round.

On Windows a file another process holds open cannot be replaced, and one being
replaced cannot be opened, for a moment: the chronometer's protocol generator, a
recorder reading the session, a virus scanner. Both sides try again for a quarter
of a second before they give up.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

TRIES = 5
PAUSE_S = 0.05


def write_in_one_step(path: Path, data: bytes) -> None:
    """A temporary file, flushed and synced, renamed over: a reader sees the old file
    or the new one, never a mix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(TRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == TRIES - 1:
                raise
            time.sleep(PAUSE_S)


def read_bytes(path: Path) -> bytes:
    """The file's bytes, read again while another process is replacing it."""
    for attempt in range(TRIES):
        try:
            return path.read_bytes()
        except PermissionError:
            if attempt == TRIES - 1:
                raise
            time.sleep(PAUSE_S)
    raise AssertionError("unreachable")  # pragma: no cover


def read_json(path: Path) -> dict[str, Any] | None:
    """A JSON object file another process replaces, such as a heartbeat; None when
    it is not there or not an object."""
    try:
        found = json.loads(read_bytes(path))
    except OSError, ValueError:
        return None
    return found if isinstance(found, dict) else None


def append(path: Path, data: bytes) -> None:
    """``data`` at the end of ``path``, synced; after a line a crash cut short, on a
    line of its own, so the two are not read as one. A file held a moment (Windows)
    is tried again."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(TRIES):
        try:
            with path.open("a+b") as f:
                end = f.seek(0, os.SEEK_END)
                if end:
                    f.seek(end - 1)
                    if f.read(1) != b"\n":
                        data = b"\n" + data
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            return
        except PermissionError:
            if attempt == TRIES - 1:
                raise
            time.sleep(PAUSE_S)


class Appended:
    """A file others append lines to, read a piece at a time: each call gives the
    complete lines added since the last, so a long race's lists are not read over
    and over. A file that got shorter is read from its start again."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0

    def new_lines(self) -> list[str]:
        try:
            with self.path.open("rb") as f:
                if f.seek(0, os.SEEK_END) < self.offset:
                    self.offset = 0
                f.seek(self.offset)
                data = f.read()
        except OSError:
            return []
        complete = data[: data.rfind(b"\n") + 1]
        self.offset += len(complete)
        lines = (
            raw.decode("utf-8", "replace").strip() for raw in complete.splitlines()
        )
        return [line for line in lines if line]
