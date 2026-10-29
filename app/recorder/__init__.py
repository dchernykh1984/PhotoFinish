"""A camera's recorder: a process of its own that keeps recording without the window.

``<photofinish> --recorder <camera id>`` reads the camera from the session, records
into ``video/<camera id>/`` and rewrites ``recorder.json`` there every second; it
stops when ``stop.request`` appears (contracts/recorder.md). A lock file keeps a
second recorder off the same camera. A camera that fails is opened again after a
pause (``Backoff``). Below 2 GB free the heartbeat says "low disk"; a write that
fails for lack of space stops the recorder with ``disk_full``.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

import av
import numpy as np

from app import session
from app.paths import app_path
from app.recorder.segments import SegmentWriter
from app.recorder.sources import CameraSettingsError, Source, open_source

LOW_DISK = 2 * 1024**3
# A heartbeat older than this: the recorder is gone. Longer than a camera open
# blocks (OPEN_TIMEOUT_S), when no heartbeat is written.
STALE_MS = 15_000
CAMERA_ID = re.compile(r"[A-Za-z0-9_-]+")


def folder_of(camera_id: str) -> Path:
    return app_path("video", camera_id)


class SteadyClock:
    """Unix milliseconds that never go back: the wall clock read at the start, then a
    steady clock, so frames keep their order when the computer's clock is set back.
    Within LEAP_MS of the computer's clock it follows it slowly, a millisecond a
    second at most, as the two oscillators drift apart over a race day. The steady
    clock stands still while the computer sleeps: when the wall clock has run ahead
    of it by more than LEAP_MS, it is read again, and the frames that follow are on
    the computer's time, as the chronometer's are."""

    LEAP_MS = 2000
    SLEW = 0.001  # the share of the time passed by which it may be brought nearer

    def __init__(self) -> None:
        self._anchor()
        self._last = int(self._wall)

    def _anchor(self) -> None:
        self._wall = time.time_ns() / 1_000_000
        self._steady = self._then = time.monotonic_ns()
        self._skew = 0.0

    def __call__(self) -> int:
        now = time.monotonic_ns()
        steady = self._wall + (now - self._steady) / 1_000_000 + self._skew
        ahead = time.time_ns() / 1_000_000 - steady
        if ahead > self.LEAP_MS:
            self._anchor()  # it slept, or its clock was set forward
            steady = self._wall
        elif ahead >= -self.LEAP_MS:  # drift; a clock set back is not followed
            most = (now - self._then) / 1_000_000 * self.SLEW
            self._skew += max(-most, min(most, ahead))
            steady = self._wall + (now - self._steady) / 1_000_000 + self._skew
        self._then = now
        self._last = max(self._last, int(steady))
        return self._last


class Backoff:
    """Pauses before trying again: 1 s, doubling to 30 s while it keeps failing, and
    1 s again once it has run 30 s."""

    def __init__(self) -> None:
        self._pause = 1.0
        self._running_since: float | None = None

    def running(self, now: float) -> None:
        if self._running_since is None:
            self._running_since = now

    def failed(self, now: float) -> float:
        if self._running_since is not None and now - self._running_since >= 30:
            self._pause = 1.0
        self._running_since = None
        pause, self._pause = self._pause, min(self._pause * 2, 30.0)
        return pause


class Heartbeat:
    """``recorder.json``: written when the state changes and at least once a second."""

    def __init__(self, folder: Path, connection: str) -> None:
        self.path = folder / "recorder.json"
        self.info: dict[str, Any] = {
            "pid": os.getpid(),
            "heartbeat_ms": 0,
            "state": "starting",
            "detail": "",
            "frames": 0,
            "segments": 0,
            "free_bytes": 0,
            "connection": connection,
        }
        self._written = 0.0

    def beat(self, **changes: Any) -> None:
        news = any(
            key in changes and self.info[key] != changes[key]
            for key in ("state", "detail")
        )
        self.info.update(changes)
        now = time.monotonic()
        if not news and now - self._written < 1:
            return
        free = shutil.disk_usage(self.path.parent).free
        low = free < LOW_DISK and self.info["state"] == "recording"
        if low or self.info["detail"] == "low disk":
            self.info["detail"] = "low disk" if low else ""
        self.info |= {"heartbeat_ms": time.time_ns() // 1_000_000, "free_bytes": free}
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self.info) + "\n", encoding="ascii")
            tmp.replace(self.path)
        except OSError:
            return  # the window reading it on Windows, or a full disk: next time
        self._written = now


class _DiskFullError(Exception):
    pass


def run(
    camera_id: str,
    clock: Callable[[], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Record the camera until ``stop.request``; the process's exit code."""
    if not CAMERA_ID.fullmatch(camera_id):
        return 2
    folder = folder_of(camera_id)
    folder.mkdir(parents=True, exist_ok=True)
    lock = _lock(folder / "recorder.lock")
    if lock is None:
        return 3  # another recorder has this camera
    with lock:
        camera = session.camera(session.load(), camera_id)
        beat = Heartbeat(folder, str((camera or {}).get("connection", "")))
        if camera is None:
            beat.beat(state="failed", detail=f"no camera {camera_id} in the session")
            return 2
        return _Recording(folder, camera, beat, clock or SteadyClock(), sleep).run()


class _Recording:
    def __init__(
        self,
        folder: Path,
        camera: dict[str, Any],
        beat: Heartbeat,
        clock: Callable[[], int],
        sleep: Callable[[float], None],
    ) -> None:
        self.folder, self.camera, self.beat = folder, camera, beat
        self.clock, self.sleep = clock, sleep
        self.stop = folder / "stop.request"
        self.writer: SegmentWriter | None = None
        self.backoff = Backoff()

    def run(self) -> int:
        try:
            while not self.stop.exists():
                self.beat.beat(state="connecting", detail="")
                try:
                    if self._record(open_source(self.camera, self.clock)):
                        break
                    detail = "the camera ended"
                except _DiskFullError, CameraSettingsError:
                    raise
                except Exception as error:  # any camera failure: try again
                    detail = str(error) or type(error).__name__
                if self._wait(detail):
                    break
            self._close()
        except _DiskFullError:
            self.beat.beat(state="disk_full", detail="the disk is full")
            return 4
        except CameraSettingsError as error:
            self.beat.beat(state="failed", detail=str(error))
            return 2
        writer = self.writer
        counts = (
            {}
            if writer is None
            else {"frames": writer.frames, "segments": writer.segments}
        )
        self.beat.beat(state="stopped", detail="", **counts)  # the last segment counted
        self.stop.unlink(missing_ok=True)
        return 0

    def _record(self, source: Source) -> bool:
        """Frames into segments; True when a stop was asked for."""
        for item in source.frames():
            if item is None:
                self.beat.beat(state="connecting", detail=source.waiting)
            else:
                self._write(source, *item)
            if self.stop.exists():
                return True
        return False

    def _write(
        self, source: Source, image: np.ndarray | av.VideoFrame | av.Packet, ms: int
    ) -> None:
        if self.writer is None:
            self.writer = SegmentWriter(self.folder, source.fps)
        writer = self.writer
        writer.fps = source.fps
        if isinstance(image, av.Packet):
            _disk(writer.write_packet, image, ms)
        else:
            _disk(writer.write, image, ms)
        self.backoff.running(time.monotonic())
        counts: dict[str, Any] = {"frames": writer.frames, "segments": writer.segments}
        if self.beat.info["state"] != "recording":
            counts["detail"] = ""  # what was said while connecting is over
        self.beat.beat(state="recording", **counts)

    def _wait(self, detail: str) -> bool:
        """The open segment closed, a pause before trying again; True when a stop
        was asked for meanwhile."""
        self._close()
        if self.writer is not None:
            self.writer.gap_reason = "reconnect"
        until = time.monotonic() + self.backoff.failed(time.monotonic())
        while time.monotonic() < until:
            self.beat.beat(state="reconnecting", detail=detail)
            if self.stop.exists():
                return True
            self.sleep(min(0.1, max(until - time.monotonic(), 0)))
        return False

    def _close(self) -> None:
        """The open segment closed. One that cannot be is left as it is -- kept aside
        when the next segment starts -- and the recording goes on; a full disk
        ends it."""
        if self.writer is None:
            return
        try:
            _disk(self.writer.close)
        except _DiskFullError:
            raise
        except (OSError, av.FFmpegError) as error:
            self.beat.beat(detail=f"a segment could not be closed: {error}")


def _disk(write: Callable[..., None], *args: Any) -> None:
    try:
        write(*args)
    except OSError as error:
        if error.errno == errno.ENOSPC:
            raise _DiskFullError from error
        raise


def _lock(path: Path) -> IO[bytes] | None:
    """The file held locked while this process lives; None when another holds it."""
    f = path.open("a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f
