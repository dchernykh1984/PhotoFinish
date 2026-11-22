"""The window's log, ``data/window.log``: what a console would have shown -- a
Python error no handler took, the stacks of a crash -- kept for a window started
from Finder or Explorer, which has none."""

from __future__ import annotations

import faulthandler
import math
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import TextIO

LIMIT_BYTES = 5_000_000  # a log past this at a start is set aside; a run's room
AGAIN_S = 60.0  # an error again within this of its writing is counted, not written


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
        self._lock = threading.Lock()  # errors come from the threads too
        self._seen: dict[str, tuple[float, int]] = {}  # an error's place: when
        # it was written, on the steady clock, how often it came since
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
    ) -> None:
        """An error no handler took, with its traceback. One from the same place
        again within AGAIN_S of its writing -- by turns with others, its words
        changed -- is counted instead: a paint failing at every frame fills no
        disk."""
        text = "".join(traceback.format_exception(kind, value, tb)).rstrip("\n")
        place = _place(kind, tb)
        now = self._steady()
        with self._lock:
            self._said_again(now)
            if place in self._seen:
                written, again = self._seen[place]
                self._seen[place] = (written, again + 1)
                return
            self._write(f"an error no handler took:\n{text}")
            self._seen[place] = (now, 0)

    def end(self) -> None:
        with self._lock:
            self._said_again(math.inf)
            self._write("the window ended", always=True)

    def _said_again(self, now: float) -> None:
        """The errors written AGAIN_S ago or more let go, how often each came since
        said."""
        for place, (written, again) in list(self._seen.items()):
            if now - written >= AGAIN_S:
                if again:
                    times = "time" if again == 1 else "times"
                    self._write(f"{place} came {again} {times} more in its minute")
                del self._seen[place]

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


def _place(kind: type[BaseException] | None, tb: TracebackType | None) -> str:
    """An error's kind and where it was raised: the same error, whatever its words
    say."""
    name = getattr(kind, "__name__", str(kind))
    frames = traceback.extract_tb(tb)
    return f"{name} at {frames[-1].filename}:{frames[-1].lineno}" if frames else name


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
    hooked, threads = sys.excepthook, threading.excepthook

    def excepthook(
        kind: type[BaseException], value: BaseException, tb: TracebackType | None
    ) -> None:
        log.error(kind, value, tb)
        hooked(kind, value, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if not issubclass(args.exc_type, SystemExit):  # Python's hook ignores it too
            log.error(args.exc_type, args.exc_value, args.exc_traceback)
        threads(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
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
