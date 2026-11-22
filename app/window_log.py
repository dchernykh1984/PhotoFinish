"""The window's log, ``data/window.log``: what a console would have shown -- a
Python error no handler took, the stacks of a crash -- kept for a window started
from Finder or Explorer, which has none."""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import TextIO

LIMIT_BYTES = 5_000_000  # past this at a start, the log starts over
AGAIN_S = 60.0  # the same error again within this is counted, not written again


class WindowLog:
    """Lines with their local time, each written out at once: a crash loses none."""

    def __init__(self, file: TextIO, clock: Callable[[], float] = time.time) -> None:
        self.file = file
        self._clock = clock
        self._lock = threading.Lock()  # errors come from the threads too
        self._last: tuple[str, float] | None = None  # the error written last, when
        self._again = 0  # how often it came since, within AGAIN_S

    def write(self, text: str) -> None:
        with self._lock:
            self._write(text)

    def error(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """An error no handler took, with its traceback; the same one again within
        AGAIN_S of its writing counted instead -- a timer's slot failing each
        second fills no disk."""
        text = "".join(traceback.format_exception(kind, value, tb)).rstrip("\n")
        now = self._clock()
        with self._lock:
            last = self._last
            if last is not None and last[0] == text and now - last[1] < AGAIN_S:
                self._again += 1
                return
            self._said_again()
            self._write(f"an error no handler took:\n{text}")
            self._last = (text, now)

    def end(self) -> None:
        with self._lock:
            self._said_again()
            self._write("the window ended")

    def _said_again(self) -> None:
        if self._again:
            times = "time" if self._again == 1 else "times"
            self._write(f"the error before came {self._again} {times} more")
            self._again = 0

    def _write(self, text: str) -> None:
        now = self._clock()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        try:
            self.file.write(f"{stamp}.{int(now * 1000) % 1000:03d} {text}\n")
            self.file.flush()
        except OSError, ValueError:  # a full disk, a file gone: the window goes on
            pass


def start(
    path: Path,
    version: str,
    enable: Callable[[TextIO], object] = faulthandler.enable,
) -> WindowLog | None:
    """The log opened -- started over past LIMIT_BYTES --, the window's start
    written, the errors no handler takes sent to it, and a crash's stacks
    (``enable``, faulthandler's). None when it cannot be opened: the window starts
    all the same."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        over = path.exists() and path.stat().st_size > LIMIT_BYTES
        file = path.open(
            "w" if over else "a",
            encoding="utf-8",
            errors="backslashreplace",
            buffering=1,
        )
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
        log.error(args.exc_type, args.exc_value, args.exc_traceback)
        threads(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    enable(file)
    return log
