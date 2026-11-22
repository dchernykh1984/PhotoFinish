"""The window's log, ``data/window.log``: what a console would have shown -- a
Python error no handler took, the stacks of a crash -- kept for a window started
from Finder or Explorer, which has none."""

from __future__ import annotations

import contextlib
import faulthandler
import math
import os
import re
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TextIO

LIMIT_BYTES = 5_000_000  # a log past this at a start is set aside; a run's room
AGAIN_S = 60.0  # an error again within this of its writing is counted, not written
SAY_S = 5.0  # how often it came, written at its first repeat, then this often
WATCH_S = 1.0  # how often the minutes are said and the crash stacks' room looked at
EXIT_WAIT_S = 1.0  # after the end, how long the log's lock is waited for, in all
NAMED_CHARS = 300  # an object Python names with an error: this much of its repr
_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")  # where an object lives -- its C++ side too


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
        self._ended = False  # an error after: at the window's exit, no crash
        self._exit_by = math.inf  # after the end, the lock waited for till then
        self._waiting: list[str] = []  # lines to write, one come in mid-write too
        self._putting = False
        self.watch: threading.Thread | None = None  # the thread watching it
        self.stopped = threading.Event()  # set at the end: the watch ends

    def write(self, text: str) -> None:
        with self._held() as taken:
            if taken:
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
        with self._held() as taken:
            if not taken:
                return
            text = "".join(traceback.format_exception(kind, value, tb)).rstrip("\n")
            way, name = _way(kind, tb)
            if about:  # a finalizer's: what Python said of it, whose
                text = f"{about}\n{text}"
                if tb is None:
                    # No way to know it by: by whose, wherever it lives. Its
                    # repeats are all of that, so its count may name it too; one
                    # known by its way may come from other objects.
                    whose = _ADDRESS.sub("", about)
                    way, name = f"{way} ({whose})", f"{name} ({whose})"
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
            heading = (
                "an error at the window's exit, after its end:"
                if self._ended
                else "an error no handler took:"
            )
            # Known before it is written: one come back in while it is -- a
            # finalizer failing the same way -- is a repeat of it.
            self._seen[way] = _Seen(now, name, said=now)
            self._write(f"{heading}\n{text}")

    def tick(self) -> None:
        """The counts of the errors whose minute has ended written now -- not at
        the next error, an hour on maybe, stamped then: the watch calls it every
        WATCH_S."""
        with self._held() as taken:
            if taken:
                self._said_again(self._steady())

    def end(self) -> None:
        """The counts said, the end written, and the watch stopped before Python
        ends: frozen there holding the lock, it would keep an error at teardown
        waiting, and the process with it."""
        with self._held() as taken:
            if taken:
                self._said_again(math.inf)
                self._write("the window ended", always=True)
            self._ended = True
            self._exit_by = time.monotonic() + EXIT_WAIT_S
        self.stopped.set()
        if self.watch is not None:
            self.watch.join(timeout=EXIT_WAIT_S)

    @contextlib.contextmanager
    def _held(self) -> Iterator[bool]:
        """True with the lock taken -- after the end, waited for till EXIT_WAIT_S
        past it, all errors together: a daemon thread Python froze at its exit
        may hold it for ever, and each error waiting its own second would keep
        the process as many."""
        wait = max(self._exit_by - time.monotonic(), 0.0) if self._ended else -1
        taken = self._lock.acquire(timeout=wait)
        try:
            yield taken
        finally:
            if taken:
                self._lock.release()

    def _said_again(self, now: float) -> None:
        """The errors written AGAIN_S ago or more let go, how often each came since
        said."""
        for way, seen in list(self._seen.items()):
            # Let go before its count is written: an error come back in while
            # it is said finds it gone, and says it no second time.
            if now - seen.written >= AGAIN_S and self._seen.pop(way, None) is seen:
                if seen.again:
                    self._write(
                        f"{seen.name} came {_times(seen.again)} more in its minute"
                    )

    def _write(self, text: str, always: bool = False) -> None:
        """A line written; an error's only while the run has room for it -- the
        first that has none says the log is full, and none is written after."""
        line = f"{self._stamp()} {text}\n"
        if not always:
            if self._full:
                return
            size = len(line.encode("utf-8", "backslashreplace"))
            if size > self._room:
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
        """A line written out at once. One come in while a line is being written --
        an error raised inside the file's own write, a finalizer's -- waits for
        that write to end: a buffered file refuses a write from inside its own."""
        self._waiting.append(line)
        if self._putting:
            return
        self._putting = True
        try:
            while self._waiting:
                text = self._waiting.pop(0)
                try:
                    self.file.write(text)
                    self.file.flush()
                except OSError, ValueError, RuntimeError:  # a full disk, a file
                    pass  # gone, a write refused: the window goes on
        finally:
            self._putting = False


def _named(thing: object) -> str:
    """An object as its repr says it, whatever its kind, up to NAMED_CHARS; by its
    kind when its repr fails."""
    try:
        text = repr(thing)
    except Exception:
        return f"<{type(thing).__name__}, its repr failing>"
    return text if len(text) <= NAMED_CHARS else f"{text[: NAMED_CHARS - 3]}..."


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
    disable: Callable[[], object] = faulthandler.disable,
) -> WindowLog | None:
    """The log opened -- one past LIMIT_BYTES kept aside as ``<name>.1``, a new one
    begun --, the window's start written, the errors no handler takes sent to it,
    and a crash's stacks (``enable``, faulthandler's; ``disable`` turns them off
    past their room). None when it cannot be opened: the window starts all the
    same."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LIMIT_BYTES:
            _set_aside(path)
        file = path.open(  # "\n" written as it is: as the run's room counts it
            "a",
            encoding="utf-8",
            errors="backslashreplace",
            newline="\n",
            buffering=1,
        )
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
        if not issubclass(kind, KeyboardInterrupt):  # Ctrl+C: a way out, no error
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
                about = f"{about}: {_named(args.object)}"
            log.error(args.exc_type, args.exc_value, args.exc_traceback, about)
        unraisable(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    sys.unraisablehook = unraisable_hook
    _keep_stacks(log, file, enable, disable)
    return log


def _keep_stacks(
    log: WindowLog,
    file: TextIO,
    enable: Callable[[TextIO], object],
    disable: Callable[[], object],
) -> None:
    """A crash's stacks written to the log, a thread watching it -- the minutes
    said, the stacks' room kept; stacks that cannot be kept, or watched, off and
    that said."""
    stacks: Callable[[], object] | None = disable  # on, to be watched
    try:
        enable(file)
    except Exception as error:
        _stacks_off(log, disable, error)
        stacks = None
    log.watch = threading.Thread(
        target=_watch, args=(log, stacks), name="the window log's size", daemon=True
    )
    try:
        log.watch.start()
    except Exception as error:  # stacks with no watch on them: none
        log.watch = None
        if stacks is not None:
            _stacks_off(log, disable, error)


def _stacks_off(
    log: WindowLog, disable: Callable[[], object], error: Exception
) -> None:
    with contextlib.suppress(Exception):
        disable()
    log.write(
        f"a crash's stacks are not written this run: {type(error).__name__}: {error}"
    )


def _watch(log: WindowLog, disable: Callable[[], object] | None) -> None:
    """Every WATCH_S the minutes ended are said (``tick``), and while the stacks
    are on the log's size looked at: faulthandler writes them outside the log's
    room -- on Windows also for an exception native code handles itself --, so
    the log grown by twice the room in this run, they are turned off and that is
    said; a size not to be had, at once. It ends with the window, or its file."""
    room = 0
    if disable is not None:
        try:
            room = os.fstat(log.file.fileno()).st_size + 2 * LIMIT_BYTES
        except (OSError, ValueError) as error:
            _stacks_off(log, disable, error)
            disable = None
    while not log.stopped.wait(WATCH_S) and not log.file.closed:
        try:
            log.tick()
            if disable is not None:
                disable = _look(log, room, disable)
        except Exception as error:  # it goes on: the minutes, the stacks' room
            with contextlib.suppress(Exception):
                log.write(f"the log's watch met {type(error).__name__}: {error}")


def _look(
    log: WindowLog, room: int, disable: Callable[[], object]
) -> Callable[[], object] | None:
    """The stacks still on, or None: the log grown past ``room``, they are turned
    off and that said; with no size to keep them in, off too -- quietly when the
    file is gone with the window."""
    try:
        size = os.fstat(log.file.fileno()).st_size
    except (OSError, ValueError) as error:
        if not log.file.closed:
            _stacks_off(log, disable, error)
        return None
    if size <= room:
        return disable
    disable()
    log.write("the log is full for this run: a crash's stacks are no longer written")
    return None


def _set_aside(path: Path) -> None:
    """The log grown past its limit kept as ``<name>.1``, the one there before
    replaced: grown by errors before a crash, it is the log that explains it. One
    that cannot be moved -- open in another window on Windows -- is written on."""
    try:
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        pass
