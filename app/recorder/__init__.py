"""A camera's recorder: a process of its own that keeps recording without the window.

``<photofinish> --recorder <camera id>`` reads the camera from the session, records
into ``video/<camera id>/`` and rewrites ``recorder.json`` there every second; it
stops when ``stop.request`` appears (contracts/recorder.md). A lock file keeps a
second recorder off the same camera. A camera that fails is opened again after a
pause (``Backoff``). Below 2 GB free the heartbeat says "low disk"; a write that
fails for lack of space stops the recorder with ``disk_full``.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import shutil
import sys
import threading
import time
from collections.abc import Callable, Collection
from pathlib import Path
from typing import IO, Any

import av
import numpy as np

from app import cameras, session
from app.paths import app_path
from app.recorder.clock_sync import ClockResponder
from app.recorder.segments import SegmentWriter, recover
from app.recorder.sources import (
    LEAP_MS,
    CameraSettingsError,
    Source,
    Stream,
    open_source,
    slewed,
)
from app.version import version

LOW_DISK = 2 * 1024**3
# A recorder asked to stop ends within a second, or a stalled read's 5 s: the one
# that takes its camera over waits this long for it.
TAKE_OVER_S = 20.0
CLOCK_RETRY_S = 5.0  # a phone's clock-exchange port another program holds: tried again
# A heartbeat older than this: the recorder is gone. Longer than a camera open
# blocks (OPEN_TIMEOUT_S), when no heartbeat is written.
STALE_MS = 15_000
CAMERA_ID = re.compile(r"[A-Za-z0-9_-]+")


def folder_of(camera_id: str) -> Path:
    return app_path("video", camera_id)


def free_ids(taken: Collection[str], count: int) -> list[str]:
    """``count`` ids for new cameras: none ``taken``, none with a recording on disk
    -- a camera removed keeps its video, which a new one must not take for its own."""
    found: list[str] = []
    n = 0
    while len(found) < count:
        n += 1
        if f"cam{n}" not in taken and not folder_of(f"cam{n}").exists():
            found.append(f"cam{n}")
    return found


class SteadyClock:
    """Unix milliseconds that never go back: the wall clock read at the start, then a
    steady clock, so frames keep their order when the computer's clock is set back.
    Within LEAP_MS of the computer's clock it follows it slowly, a millisecond a
    second at most, as the two oscillators drift apart over a race day. The steady
    clock stands still while the computer sleeps: when the wall clock has run ahead
    of it by more than LEAP_MS, it is read again, and the frames that follow are on
    the computer's time, as the chronometer's are. ``micros`` reads it to the
    microsecond for the phone's clock exchange, from a thread of its own."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._anchor()
        self._last = int(self._wall)

    def _anchor(self) -> None:
        self._wall = time.time_ns() / 1_000_000
        self._steady = self._then = time.monotonic_ns()
        self._skew = 0.0

    def __call__(self) -> int:
        with self._lock:
            self._last = max(self._last, int(self._now_ms()))
            return self._last

    def micros(self) -> int:
        """The clock now in Unix microseconds. It keeps the clock near the
        computer's as a call does: a phone stamping every frame leaves the
        exchange the only reader."""
        with self._lock:
            return round(self._now_ms() * 1000)

    def _now_ms(self) -> float:
        now = time.monotonic_ns()
        steady = self._wall + (now - self._steady) / 1_000_000 + self._skew
        ahead = time.time_ns() / 1_000_000 - steady
        if ahead > LEAP_MS:
            self._anchor()  # it slept, or its clock was set forward
            steady = self._wall
        elif ahead >= -LEAP_MS:  # drift; a clock set back is not followed
            self._skew = slewed(self._skew, ahead, (now - self._then) / 1_000_000)
            steady = self._wall + (now - self._steady) / 1_000_000 + self._skew
        self._then = now
        return steady


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
            "clock": "",  # why a phone's clock exchange is left out; "" when it is not
            # A phone's last status and when it came (specs/005): the one a recorder
            # before this one heard, until the phone is heard again.
            "phone": _last_phone(self.path),
            "frames": 0,
            "segments": 0,
            "free_bytes": 0,
            "connection": connection,
            # How far the newest frame is behind this recorder's clock: a phone
            # catching up after a break (specs/007).
            "behind_ms": 0,
            # The program it runs: a window of another replaces it (specs/007).
            "version": version(),
        }
        self._written = 0.0

    def beat(self, **changes: Any) -> None:
        news = any(
            key in changes and self.info[key] != changes[key]
            for key in ("state", "detail", "clock")
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
        # Not files.write_in_one_step: its pauses and sync would hold up the frames.
        data = (json.dumps(self.info) + "\n").encode("ascii")
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(self.path)
        except OSError as error:
            # A full disk takes no new file: written over in place, in the space it
            # has, so "disk full" reaches the window. Else held on Windows: the next.
            if error.errno != errno.ENOSPC or not _in_place(self.path, data):
                return
        self._written = now


def _last_phone(path: Path) -> dict[str, Any]:
    """The phone status in a heartbeat left behind; {} when it holds none."""
    try:
        phone = json.loads(path.read_text()).get("phone")
    except OSError, ValueError, AttributeError:
        return {}
    return phone if isinstance(phone, dict) else {}


def _in_place(path: Path, data: bytes) -> bool:
    """``data`` over the file where it is, in the space it already has on disk."""
    try:
        with path.open("r+b") as f:
            f.write(data)
            f.truncate()
    except OSError:
        return False
    return True


class _DiskFullError(Exception):
    pass


def run(
    camera_id: str,
    clock: SteadyClock | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Record the camera until ``stop.request``; the process's exit code."""
    if not CAMERA_ID.fullmatch(camera_id):
        return 2
    folder = folder_of(camera_id)
    folder.mkdir(parents=True, exist_ok=True)
    lock = _lock(folder / "recorder.lock") or _take_over(folder, sleep)
    if lock is None:
        return 3  # another recorder has this camera
    with lock:
        camera = session.camera(session.load(), camera_id)
        beat = Heartbeat(folder, str((camera or {}).get("connection", "")))
        beat.beat(state="starting")  # its own word, not the dead one's, as it recovers
        closed = None  # then the writer tries again, and says what stops it
        with contextlib.suppress(Exception):
            closed = recover(folder)  # a crash's frames, shown before the camera
        if camera is None:
            beat.beat(state="failed", detail=f"no camera {camera_id} in the session")
            return 2
        return _Recording(
            folder, camera, beat, clock or SteadyClock(), sleep, closed
        ).run()


class _Recording:
    def __init__(
        self,
        folder: Path,
        camera: dict[str, Any],
        beat: Heartbeat,
        clock: SteadyClock,
        sleep: Callable[[float], None],
        closed: list[str] | None = None,  # the segments as the start found them
    ) -> None:
        self.folder, self.camera, self.beat = folder, camera, beat
        self.clock, self.sleep = clock, sleep
        self.stop = folder / "stop.request"
        self.writer: SegmentWriter | None = None
        self.closed = closed
        self.backoff = Backoff()
        self.responder: ClockResponder | None = None
        self.phone = camera.get("connection") == "rtmp"  # a phone answers the clock
        self.clock_tried = -CLOCK_RETRY_S  # time.monotonic() of the last try
        self.port_taken = ""  # why the exchange is left out: its port, taken
        self.newest_ms: int | None = None  # the newest frame's moment so far

    def _answer_the_clock(self) -> None:
        """A phone's clock exchange answered on its port. A port another program
        holds is tried again every CLOCK_RETRY_S, the phone streaming or not, and
        recorder.json's ``clock`` says so meanwhile, which the camera list shows:
        the phone's frames are then placed by their arrival."""
        if self.responder is not None or not self.phone:
            return
        now = time.monotonic()
        if now - self.clock_tried < CLOCK_RETRY_S:
            return
        self.clock_tried = now
        port = self.camera["settings"].get("port", cameras.RTMP_PORT)
        try:
            self.responder = ClockResponder(port, self.clock.micros)
            self.port_taken = ""
        except OSError as error:
            self.port_taken = (
                f"UDP port {port} is taken ({error.strerror or error}): "
                "the phone's frames are placed by their arrival"
            )

    def run(self) -> int:
        try:
            return self._run()
        finally:
            if self.responder is not None:
                self.responder.close()

    def _run(self) -> int:
        try:
            while not self.stop.exists():
                self.beat.beat(state="connecting", detail="", clock=self.port_taken)
                try:
                    source = open_source(self.camera, self.clock)  # settings checked
                    self._answer_the_clock()
                    if self._record(source):
                        break
                    if isinstance(source, Stream) and source.listen:
                        # A phone that hung up is listened for again at once: nothing
                        # is hammered, and it may be back in a moment, with its clock.
                        self._hung_up()
                        continue
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
                self._answer_the_clock()  # open before the phone's first frame
                self.beat.beat(
                    state="connecting", detail=source.waiting, clock=self.port_taken
                )
            else:
                self._write(source, *item)
            if self.stop.exists():
                return True
        return False

    def _write(
        self, source: Source, image: np.ndarray | av.VideoFrame | av.Packet, ms: int
    ) -> None:
        if self.writer is None:  # its own recovery writes too: a full disk said so
            self.writer = _disk(
                lambda: SegmentWriter(self.folder, source.fps, closed=self.closed)
            )
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
        clock = self.port_taken or source.clock_note
        self.newest_ms = ms if self.newest_ms is None else max(self.newest_ms, ms)
        counts["behind_ms"] = max(self.clock() - self.newest_ms, 0)
        self.beat.beat(state="recording", clock=clock, phone=source.phone, **counts)
        self._answer_the_clock()  # returns at its first check once open

    def _hung_up(self) -> None:
        """The open segment closed, as at a reconnect, with no pause after it."""
        self._close()
        if self.writer is not None:
            self.writer.hung_up()

    def _wait(self, detail: str) -> bool:
        """The open segment closed, a pause before trying again; True when a stop
        was asked for meanwhile."""
        self._hung_up()
        until = time.monotonic() + self.backoff.failed(time.monotonic())
        while time.monotonic() < until:
            self.beat.beat(state="reconnecting", detail=detail, clock=self.port_taken)
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
            _disk(self.writer.close)  # a full disk raises _DiskFullError: not caught
        except (OSError, av.FFmpegError) as error:
            self.beat.beat(detail=f"a segment could not be closed: {error}")


def _disk[T](write: Callable[..., T], *args: Any) -> T:
    try:
        return write(*args)
    except OSError as error:
        if error.errno == errno.ENOSPC:
            raise _DiskFullError from error
        raise


def _take_over(folder: Path, sleep: Callable[[float], None]) -> IO[bytes] | None:
    """The camera's lock, once the recorder that holds it has heard the stop asked of
    it: a window replacing a recorder of another version starts this one as it asks,
    so the camera records on whatever becomes of the window (specs/007). None when no
    stop was asked, or the other kept the camera TAKE_OVER_S."""
    stop = folder / "stop.request"
    if not stop.exists():
        return None
    deadline = time.monotonic() + TAKE_OVER_S
    while time.monotonic() < deadline:
        sleep(0.1)
        lock = _lock(folder / "recorder.lock")
        if lock is not None:
            stop.unlink(missing_ok=True)  # the other's, left by one that died
            return lock
    return None


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
