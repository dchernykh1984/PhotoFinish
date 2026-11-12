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

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import app
from app import files, paths
from app.recorder import STALE_MS, Backoff, folder_of
from app.version import version

ENDED = ("stopped", "failed", "disk_full")
START_GRACE_S = 30  # a frozen onefile build unpacks itself before its first heartbeat
# How long a window waits, before it is shown, for the recorders of another version it
# asked to stop: a recorder stops within a second, or a stalled read's 5 s.
REPLACE_WAIT_S = 5.0


def command(camera_id: str, role: str = "--recorder") -> list[str]:
    """How this program runs a camera's recorder, or its analyser."""
    if getattr(sys, "frozen", False):
        return [sys.executable, role, camera_id]
    return [sys.executable, "-m", "app.main", role, camera_id]


def package_root() -> str:
    """Where the ``app`` package is, for a process run from the sources."""
    return str(Path(app.__file__).resolve().parents[1])


def child_environment() -> dict[str, str]:
    """This environment for a process of this program started from it: in
    development the package on its path; frozen, an instance of its own -- a
    onefile build otherwise runs it from this process's unpacked files, which are
    deleted when this process ends."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    else:
        env["PYTHONPATH"] = package_root()
    return env


def spawn(camera_id: str) -> subprocess.Popen[bytes]:
    """A recorder started apart from this process; its output goes to
    ``recorder.log`` in the camera's folder."""
    folder = folder_of(camera_id)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "recorder.log").open("ab") as log:
        options: dict[str, Any] = {
            "cwd": paths.base_dir(),
            "env": child_environment(),
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
    """The recorder's last heartbeat, fresh or not; None when there is none. Read
    again while the recorder is replacing it (Windows): not a recorder gone."""
    return files.read_json(folder_of(camera_id) / "recorder.json")


def alive(info: dict[str, Any] | None) -> bool:
    """A recorder that is running: a fresh heartbeat, a state that is not an end."""
    if info is None or info.get("state") in ENDED:
        return False
    return time.time_ns() // 1_000_000 - int(info.get("heartbeat_ms", 0)) <= STALE_MS


def recording(info: dict[str, Any] | None) -> bool:
    """A recorder writing its camera's frames now: running, and recording -- not
    starting, waiting for the camera or connecting again after a loss."""
    return info is not None and info.get("state") == "recording" and alive(info)


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
        self._started_ms = 0  # wall clock, when it last tried to
        self._retry_at: float | None = None
        # The end of a recorder this window started, first seen (monotonic), which one,
        # and the heartbeat then: a later one is another recorder's.
        self._died_at: float | None = None
        self._dead: subprocess.Popen[bytes] | None = None
        self._died_beat: int | None = None
        self.error = ""  # why the recorder could not be started, until one is
        # The program of a running recorder being replaced by this one's (specs/007):
        # "" when none is.
        self.replacing = ""

    def start(self) -> None:
        """Record: attach to a running recorder, or start one. A stop asked before,
        and not yet heard, is withdrawn either way. A running recorder of another
        version is asked to stop, and replaced once it has (``poll``)."""
        self.wanted = True
        self._retry_at = None
        (folder_of(self.camera_id) / "stop.request").unlink(missing_ok=True)
        info = heartbeat(self.camera_id)
        if self._running(info):
            self.replacing = ""  # one this window started is of its own program
            if info is not None and self._process is None:
                self.replacing = _another_program(info)
            if self.replacing:
                (folder_of(self.camera_id) / "stop.request").touch()
            return
        self._started_ms = time.time_ns() // 1_000_000  # an end before: not its own
        try:
            self._process = (self._spawn or spawn)(self.camera_id)
        except OSError as error:  # moved, or blocked: tried again after the pause
            self.error = str(error)  # the dead one kept: its beat not taken for alive
            return
        self.error = ""
        self._started = time.monotonic()

    def stop(self) -> None:
        """Ask the recorder to close its segment and end."""
        self.wanted = False
        folder = folder_of(self.camera_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "stop.request").touch()

    def finish_replacing(
        self, deadline: float, sleep: Callable[[float], None] | None = None
    ) -> None:
        """A recorder being replaced waited for until ``deadline`` (monotonic), and
        this one's started as soon as it has ended: the window does so before it is
        shown, as one closed or lost at once would leave the camera with no recorder.
        One still running then is left to ``poll``."""
        while self.replacing and time.monotonic() < deadline:
            (sleep or time.sleep)(0.1)
            self.poll()

    def poll(self) -> dict[str, Any] | None:
        """The heartbeat, for the window; a dead recorder is started again after
        the pause, one being replaced at once once it has ended."""
        info = heartbeat(self.camera_id)
        now = time.monotonic()
        if self.replacing:
            if alive(info):
                return info
            self.replacing = ""
            if self.wanted:
                self.start()
            return info
        if self._running(info):
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

    def _running(self, info: dict[str, Any] | None) -> bool:
        """A fresh heartbeat, unless the recorder this window started has ended without
        saying why: then it is gone at once, not 15 s later -- unless the heartbeat
        has changed since, written by a recorder that lives. A start that found the
        camera locked (3) leaves it to the heartbeat, but not within 15 s of such an
        end with no beat since: the lock may still be the dead one's (Windows lets go
        of it late). Each one's end is marked, one that beat and died between two
        polls too, with the heartbeat read once that end is seen: a beat it wrote
        just before is its own. No pid is guessed: a frozen build fronts it."""
        process = self._process
        code = None if process is None else process.poll()
        if code is None:
            return alive(info)
        now = time.monotonic()
        if code != 3 and self._dead is not process:
            info = heartbeat(self.camera_id)  # read since its end: no beat of it after
            if info is None:
                return False  # unread: its end marked at the next poll, read again
            self._died_at, self._dead = now, process
            self._died_beat = int(info.get("heartbeat_ms", 0))
        beat_ms = 0 if info is None else int(info.get("heartbeat_ms", 0))
        beating = beat_ms != self._died_beat  # since that end: another recorder's
        if code != 3:
            return beating and alive(info)
        died = self._died_at is not None and now - self._died_at < STALE_MS / 1000
        return (beating or not died) and alive(info)

    def _ended_by_itself(self, info: dict[str, Any] | None) -> bool:
        """Failed, or the disk full, since this window started it: left for the
        referee. One that stopped heard a stop, maybe just before it was withdrawn:
        started again while it is wanted."""
        return (
            info is not None
            and info.get("state") in ("failed", "disk_full")
            and int(info.get("heartbeat_ms", 0)) >= self._started_ms
        )

    def _starting(self, now: float) -> bool:
        process = self._process
        return (
            process is not None
            and process.poll() is None
            and now - self._started < START_GRACE_S
        )


def _another_program(info: dict[str, Any]) -> str:
    """The program a recorder runs, as the camera's line names it, when it is not
    this one: of another version, or of none (0.6.0 and before); "" when it is this
    one, or this one cannot tell its own."""
    mine, theirs = version(), str(info.get("version") or "")
    if not mine or theirs == mine:
        return ""
    return f"PhotoFinish {theirs}" if theirs else "an older PhotoFinish"


_STATES = {"disk_full": "disk full, recording stopped"}
BEHIND_SAID_MS = 2000  # a phone this far behind live is catching up: said


def describe(info: dict[str, Any] | None) -> str:
    """The recorder's state as the camera list says it."""
    if info is None:
        return "not started"
    state, detail = str(info.get("state", "")), str(info.get("detail", ""))
    if state not in ENDED and not alive(info):
        return "not responding"
    if state == "recording":
        text = f"recording, {info.get('frames', 0)} frames"
        text = f"{text}, under 2 GB free" if detail == "low disk" else text
        behind = int(info.get("behind_ms") or 0)
        if behind >= BEHIND_SAID_MS:
            text = f"{text}, {behind // 1000} s behind"
    else:
        text = _STATES.get(state, state)
        text = f"{text}: {detail}" if detail else text
    # Why a phone's frames are placed by their arrival, while it records or waits.
    clock = "" if state in ENDED else str(info.get("clock", ""))
    return f"{text}; {clock}" if clock else text
