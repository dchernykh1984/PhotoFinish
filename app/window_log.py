"""The window's log, ``data/window.log``: what a console would have shown -- a
Python error no handler took, the stacks of a crash -- kept for a window started
from Finder or Explorer, which has none."""

from __future__ import annotations

import contextlib
import faulthandler
import math
import os
import re
import reprlib
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TextIO

LIMIT_BYTES = 5_000_000  # a log past this at a start is set aside; a run's room
AGAIN_S = 60.0  # an error again within this of its writing is counted, not written
SAY_S = 5.0  # how often it came, written at its first repeat, then this often
_NAMED = reprlib.Repr(maxother=300)  # an object named whole, a repr that fails too
_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")  # where an object lives, not what


@dataclass
class _Seen:
    """An error written: when, on the steady clock; how often it came since, and
    when that was last written."""

    written: float
    name: str
    again: int = 0
    said: float = 0.0


class WindowLog:
    """Lines with their local time, each written out at once: a crash loses none."""

    def __init__(
        self,
        file: TextIO,
        clock: Callable[[], float] = time.time,
        steady: Callable[[], float] = time.monotonic,
    ) -> None:
        self.file = file
        self._clock = clock  # the lines' times
        self._steady = steady  # an error's minute: a clock set back stops neither
        # Errors come from the threads too, and one raised while this thread
        # writes -- a finalizer's, the collector runs it there -- comes back in:
        # it is written, the lock taken again, no longer waited on for ever.
        self._lock = threading.RLock()
        self._seen: dict[str, _Seen] = {}  # by the way each error came
        self._room = LIMIT_BYTES  # what this run may still write of its errors
        self._full = False

    def write(self, text: str) -> None:
        with self._lock:
            self._write(text, always=True)

    def error(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        tb: TracebackType | None,
        about: str = "",
    ) -> None:
        """An error no handler took, with its traceback and what Python said
        ``about`` it. One come the same way again within AGAIN_S of its writing --
        by turns with others, its words changed -- is counted instead: a paint
        failing at every frame fills no disk."""
        with self._lock:
            text = "".join(traceback.format_exception(kind, value, tb)).rstrip("\n")
            way, name = _way(kind, tb)
            if about:  # a finalizer's: what Python said of it, whose
                text, name = f"{about}\n{text}", f"{name} ({about})"
                if tb is None:  # no way to know it by: by whose, then, wherever
                    way = f"{way} ({_ADDRESS.sub('', about)})"  # it lives
            now = self._steady()
            self._said_again(now)
            seen = self._seen.get(way)  # an error come back in may have let it go
            if seen is not None:
                seen.again += 1
                # A crash ends the minute unsaid: how often is written on the way.
                if seen.again == 1 or now - seen.said >= SAY_S:
                    seen.said = now
                    self._write(f"{seen.name} came {_times(seen.again)} more so far")
                return
            self._write(f"an error no handler took:\n{text}")
            self._seen[way] = _Seen(now, name, said=now)

    def end(self) -> None:
        with self._lock:
            self._said_again(math.inf)
            self._write("the window ended", always=True)

    def _said_again(self, now: float) -> None:
        """The errors written AGAIN_S ago or more let go, how often each came since
        said."""
        for way, seen in list(self._seen.items()):
            if now - seen.written >= AGAIN_S:
                if seen.again:
                    self._write(
                        f"{seen.name} came {_times(seen.again)} more in its minute"
                    )
                self._seen.pop(way, None)  # let go already by an error come in

    def _write(self, text: str, always: bool = False) -> None:
        """A line written; an error's only while the run has room for it -- once it
        has not, that is said, once."""
        line = f"{self._stamp()} {text}\n"
        if not always:
            size = len(line.encode("utf-8", "backslashreplace"))
            if size > self._room:
                if not self._full:
                    self._full = True
                    self._put(
                        f"{self._stamp()} the log is full for this run: no more "
                        "of its errors are written\n"
                    )
                return
            self._room -= size
        self._put(line)

    def _stamp(self) -> str:
        now = self._clock()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        return f"{stamp}.{int(now * 1000) % 1000:03d}"

    def _put(self, line: str) -> None:
        try:
            self.file.write(line)
            self.file.flush()
        except OSError, ValueError:  # a full disk, a file gone: the window goes on
            pass


def _times(count: int) -> str:
    return f"{count} time" if count == 1 else f"{count} times"


def _way(kind: type[BaseException] | None, tb: TracebackType | None) -> tuple[str, str]:
    """An error known by its kind and the lines it came through -- the same
    whatever its words say, another when it came another way to the line that
    raised it -- and named by its kind and that line."""
    name = getattr(kind, "__name__", str(kind))
    lines = [f"{frame.filename}:{frame.lineno}" for frame in traceback.extract_tb(tb)]
    if not lines:
        return name, name
    return f"{name} at {' < '.join(reversed(lines))}", f"{name} at {lines[-1]}"


def start(
    path: Path,
    version: str,
    enable: Callable[[TextIO], object] = faulthandler.enable,
) -> WindowLog | None:
    """The log opened -- one past LIMIT_BYTES kept aside as ``<name>.1``, a new one
    begun --, the window's start written, the errors no handler takes sent to it,
    and a crash's stacks (``enable``, faulthandler's). None when it cannot be
    opened: the window starts all the same."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LIMIT_BYTES:
            _set_aside(path)
        file = path.open("a", encoding="utf-8", errors="backslashreplace", buffering=1)
    except OSError:
        return None
    log = WindowLog(file)
    log.write(
        f"PhotoFinish {version or '(version unknown)'} started, pid {os.getpid()}"
    )
    hooked, threads, unraisable = (
        sys.excepthook,
        threading.excepthook,
        sys.unraisablehook,
    )

    # Each error handed on to the hook before whatever the log does: a failure
    # of its own -- a traceback too deep to format -- loses the error nowhere.
    def excepthook(
        kind: type[BaseException], value: BaseException, tb: TracebackType | None
    ) -> None:
        with contextlib.suppress(Exception):
            log.error(kind, value, tb)
        hooked(kind, value, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if not issubclass(args.exc_type, SystemExit):  # Python's hook ignores it too
            with contextlib.suppress(Exception):
                log.error(args.exc_type, args.exc_value, args.exc_traceback)
        threads(args)

    def unraisable_hook(args: sys.UnraisableHookArgs) -> None:
        # In a finalizer, a weakref's callback: Python prints these to a stderr
        # a window started from Finder or Explorer does not have.
        with contextlib.suppress(Exception):
            about = args.err_msg or "Exception ignored in"
            if args.object is not None:
                about = f"{about}: {_NAMED.repr(args.object)}"
            log.error(args.exc_type, args.exc_value, args.exc_traceback, about)
        unraisable(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    sys.unraisablehook = unraisable_hook
    enable(file)
    return log


def _set_aside(path: Path) -> None:
    """The log grown past its limit kept as ``<name>.1``, the one there before
    replaced: grown by errors before a crash, it is the log that explains it. One
    that cannot be moved -- open in another window on Windows -- is written on."""
    try:
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        pass
