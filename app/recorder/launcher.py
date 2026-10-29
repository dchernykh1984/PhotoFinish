"""The window's side of a recorder: start it detached, attach to it, restart it.

A recorder runs as ``<photofinish> --recorder <camera id>`` in a session of its own
(``start_new_session`` on POSIX; a detached process in a new group on Windows,
leaving the window's job when the job allows it), so killing the window does not
stop it. The window attaches to a recorder whose heartbeat is fresh and starts one
otherwise; a recorder found dead is started again after the backoff pause, and one
that ended by itself -- stopped, failed, disk full -- is left for the referee.
Stopping is ``stop.request``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import app
from app import paths
from app.recorder import STALE_MS, Backoff, folder_of

ENDED = ("stopped", "failed", "disk_full")
START_GRACE_S = 30  # a frozen onefile build unpacks itself before its first heartbeat


def command(camera_id: str, role: str = "--recorder") -> list[str]:
    """How this program runs a camera's recorder, or its analyser."""
    if getattr(sys, "frozen", False):
        return [sys.executable, role, camera_id]
    return [sys.executable, "-m", "app.main", role, camera_id]


def package_root() -> str:
    """Where the ``app`` package is, for a process run from the sources."""
    return str(Path(app.__file__).resolve().parents[1])


def spawn(camera_id: str) -> subprocess.Popen[bytes]:
    """A recorder started apart from this process; its output goes to
    ``recorder.log`` in the camera's folder."""
    folder = folder_of(camera_id)
    folder.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if not getattr(sys, "frozen", False):
        env["PYTHONPATH"] = package_root()
    with (folder / "recorder.log").open("ab") as log:
        options: dict[str, Any] = {
            "cwd": paths.base_dir(),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": log,
        }
        if sys.platform != "win32":
            return subprocess.Popen(  # noqa: S603 - this program, by its own path
                command(camera_id), start_new_session=True, **options
            )
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(  # noqa: S603
                command(camera_id),
                creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                **options,
            )
        except OSError:  # the window's job does not let its processes leave
            return subprocess.Popen(  # noqa: S603
                command(camera_id), creationflags=flags, **options
            )


def heartbeat(camera_id: str) -> dict[str, Any] | None:
    """The recorder's last heartbeat, fresh or not; None when there is none."""
    try:
        info = json.loads((folder_of(camera_id) / "recorder.json").read_text())
    except OSError, ValueError:
        return None
    return info if isinstance(info, dict) else None


def alive(info: dict[str, Any] | None) -> bool:
    """A recorder that is running: a fresh heartbeat, a state that is not an end."""
    if info is None or info.get("state") in ENDED:
        return False
    return time.time_ns() // 1_000_000 - int(info.get("heartbeat_ms", 0)) <= STALE_MS


class Watchdog:
    """One camera's recorder kept running while the window wants it; the window
    calls ``poll`` every second."""

    def __init__(
        self,
        camera_id: str,
        spawn: Callable[[str], subprocess.Popen[bytes]] | None = None,
    ) -> None:
        self.camera_id, self._spawn = camera_id, spawn  # None: this module's spawn
        self.wanted = False
        self.backoff = Backoff()
        self._process: subprocess.Popen[bytes] | None = None
        self._started = 0.0  # monotonic, when this window last started one
        self._started_ms = 0  # wall clock, the same moment
        self._retry_at: float | None = None

    def start(self) -> None:
        """Record: attach to a running recorder, or start one. A stop asked before,
        and not yet heard, is withdrawn either way."""
        self.wanted = True
        self._retry_at = None
        (folder_of(self.camera_id) / "stop.request").unlink(missing_ok=True)
        if alive(heartbeat(self.camera_id)):
            return
        self._process = (self._spawn or spawn)(self.camera_id)
        self._started = time.monotonic()
        self._started_ms = time.time_ns() // 1_000_000

    def stop(self) -> None:
        """Ask the recorder to close its segment and end."""
        self.wanted = False
        folder = folder_of(self.camera_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "stop.request").touch()

    def poll(self) -> dict[str, Any] | None:
        """The heartbeat, for the window; a dead recorder is started again after
        the pause."""
        info = heartbeat(self.camera_id)
        now = time.monotonic()
        if alive(info):
            self.backoff.running(now)
            self._retry_at = None
            return info
        if not self.wanted or self._ended_by_itself(info) or self._starting(now):
            return info
        if self._retry_at is None:
            self._retry_at = now + self.backoff.failed(now)
        elif now >= self._retry_at:
            self.start()
        return info

    def _ended_by_itself(self, info: dict[str, Any] | None) -> bool:
        return (
            info is not None
            and info.get("state") in ENDED
            and int(info.get("heartbeat_ms", 0)) >= self._started_ms
        )

    def _starting(self, now: float) -> bool:
        process = self._process
        return (
            process is not None
            and process.poll() is None
            and now - self._started < START_GRACE_S
        )


_STATES = {"disk_full": "disk full, recording stopped"}


def describe(info: dict[str, Any] | None) -> str:
    """The recorder's state as the camera list says it."""
    if info is None:
        return "not started"
    state, detail = str(info.get("state", "")), str(info.get("detail", ""))
    if state not in ENDED and not alive(info):
        return "not responding"
    if state == "recording":
        text = f"recording, {info.get('frames', 0)} frames"
        return f"{text}, under 2 GB free" if detail == "low disk" else text
    text = _STATES.get(state, state)
    return f"{text}: {detail}" if detail else text
