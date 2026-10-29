"""The session: what a restart resumes, ``data/session.json`` next to the program.

Recorders read their camera's settings from it while the window writes it, so it is
replaced in one step: a reader sees the old file or the new one, never a mix. Keys
this version does not know are kept as they were.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

from app import files
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
    "analysis": {"on": False, "model": ""},  # specs/002: experimental, off by default
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
        saved = json.loads(files.read_bytes(path).decode("utf-8"))
    except FileNotFoundError:
        return session
    except ValueError:  # not JSON, or not UTF-8: not a session
        saved = None
    # Any other OSError is raised: a file that cannot be read now is no broken one.
    if not isinstance(saved, dict):
        path.replace(path.with_name(f"{path.name}.broken-{int(time.time() * 1000)}"))
        return session
    session.update(saved)
    return session


def save(session: dict[str, Any]) -> None:
    """Write the session in one step: a temporary file, flushed, then renamed over."""
    text = json.dumps(session, indent=2, ensure_ascii=False) + "\n"
    files.write_in_one_step(session_path(), text.encode("utf-8"))


def camera(session: dict[str, Any], camera_id: str) -> dict[str, Any] | None:
    """The camera with that id, or None."""
    return next((c for c in session["cameras"] if c.get("id") == camera_id), None)
