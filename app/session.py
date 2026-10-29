"""The session: what a restart resumes, ``data/session.json`` next to the program.

Recorders read their camera's settings from it while the window writes it, so it is
replaced in one step: a reader sees the old file or the new one, never a mix. Keys
this version does not know are kept as they were.
"""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path
from typing import Any

from app.paths import app_path

VERSION = 1

DEFAULTS: dict[str, Any] = {
    "version": VERSION,
    "input": "",
    "output": "",
    "summer_time": False,
    "finish_mode": False,
    "source_offset_ms": 0,
    "cameras": [],
    "input_taken": [],
    "input_changes": [],
}


def session_path() -> Path:
    return app_path("data", "session.json")


def load() -> dict[str, Any]:
    """The saved session over the defaults. A file that is not a session is moved
    aside, ``session.json.broken-<ms>``, and the defaults are used: nothing in it is
    lost, and the window still starts."""
    path = session_path()
    session = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return session
    except OSError, ValueError:
        saved = None
    if not isinstance(saved, dict):
        path.replace(path.with_name(f"{path.name}.broken-{int(time.time() * 1000)}"))
        return session
    session.update(saved)
    return session


def save(session: dict[str, Any]) -> None:
    """Write the session in one step: a temporary file, flushed, then renamed over."""
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def camera(session: dict[str, Any], camera_id: str) -> dict[str, Any] | None:
    """The camera with that id, or None."""
    return next((c for c in session["cameras"] if c.get("id") == camera_id), None)
