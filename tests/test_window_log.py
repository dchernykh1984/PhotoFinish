"""The window's log: its starts, the errors no handler took, a crash's stacks."""

from __future__ import annotations

import io
import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Any

import pytest

from app import window_log

type Raised = tuple[type[BaseException], BaseException, TracebackType | None]


def raised(text: str) -> Raised:
    try:
        raise ValueError(text)
    except ValueError as error:
        return type(error), error, error.__traceback__


def raised_elsewhere(text: str) -> Raised:
    try:
        raise KeyError(text)
    except KeyError as error:
        return type(error), error, error.__traceback__


@pytest.fixture(autouse=True)
def closed_after(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each log a test starts closed after it: its watch ends, its file is let
    go -- Windows deletes no file still open."""
    started: list[window_log.WindowLog] = []
    real = window_log.start

    def start(*args: Any, **kwargs: Any) -> window_log.WindowLog | None:
        log = real(*args, **kwargs)
        if log is not None:
            started.append(log)
        return log

    monkeypatch.setattr(window_log, "start", start)
    yield
    for log in started:
        log.file.close()


@pytest.fixture
def hooks(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """The hooks before the log's: what they were called with; put back after."""
    called: list[object] = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: called.append(error[0]))
    monkeypatch.setattr(threading, "excepthook", lambda a: called.append(a.exc_type))
    monkeypatch.setattr(sys, "unraisablehook", lambda a: called.append(a.exc_type))
    return called


def test_the_window_s_errors_go_to_its_log_and_on_to_the_hooks_before(
    tmp_path: Path, hooks: list[object]
) -> None:
    enabled: list[object] = []
    path = tmp_path / "data" / "window.log"
    log = window_log.start(path, "9.9.9", enable=enabled.append, disable=lambda: None)
    assert log is not None
    assert enabled == [log.file]  # a crash's stacks: faulthandler writes them there
    sys.excepthook(*raised("in a slot"))
    thread = threading.Thread(target=lambda: 1 / 0)
    thread.start()
    thread.join()
    log.end()
    text = path.read_text(encoding="utf-8")
    assert "PhotoFinish 9.9.9 started, pid " in text
    assert "ValueError: in a slot" in text
    assert "ZeroDivisionError" in text
    assert text.rstrip().endswith("the window ended")
    assert hooks == [ValueError, ZeroDivisionError]  # the console's still told


def test_a_thread_ending_by_system_exit_is_no_error(
    tmp_path: Path, hooks: list[object]
) -> None:
    # Python's own hook lets SystemExit from a thread pass in silence: no fault to
    # send anyone looking for.
    path = tmp_path / "window.log"
    assert (
        window_log.start(path, "1.0.0", enable=lambda file: None, disable=lambda: None)
        is not None
    )
    thread = threading.Thread(target=sys.exit)
    thread.start()
    thread.join()
    assert "SystemExit" not in path.read_text(encoding="utf-8")
    assert hooks == [SystemExit]  # the hook before still asked


def test_the_same_error_again_within_a_minute_is_counted_not_written() -> None:
    # A timer's slot failing each second: written once a minute, how often between.
    file = io.StringIO()
    now = [1000.0]
    log = window_log.WindowLog(file, clock=lambda: now[0], steady=lambda: now[0])
    for second in range(62):
        now[0] = 1000.0 + second
        log.error(*raised("each second"))
    log.end()
    text = file.getvalue()
    assert text.count("ValueError: each second") == 2  # at 0 s and at 60 s
    assert "came 59 times more" in text
    assert "came 1 time more" in text  # at 61 s, said at the end
    assert text.rstrip().endswith("the window ended")


def test_errors_by_turns_or_in_changing_words_are_each_written_once_a_minute() -> None:
    # Two paints failing by turns, or one naming a moment that changes: none of
    # them the error just before, all of them repeats of one from the same place.
    file = io.StringIO()
    now = [1000.0]
    log = window_log.WindowLog(file, clock=lambda: now[0], steady=lambda: now[0])
    for second in range(30):
        now[0] = 1000.0 + second
        log.error(*raised(f"at {second}"))
        log.error(*raised_elsewhere("frame"))
    log.end()
    text = file.getvalue()
    assert text.count("ValueError: at ") == 1
    assert text.count("KeyError: 'frame'") == 1
    assert text.count("came 29 times more") == 2


def test_a_run_writes_errors_up_to_its_room(monkeypatch: pytest.MonkeyPatch) -> None:
    # Errors that do not repeat fill no disk either: a run past its room says so
    # once and writes no more of them; its end is still said.
    monkeypatch.setattr(window_log, "LIMIT_BYTES", 3000)
    file = io.StringIO()
    now = [1000.0]
    log = window_log.WindowLog(file, clock=lambda: now[0], steady=lambda: now[0])
    for minute in range(100):
        now[0] = 1000.0 + 61 * minute
        log.error(*raised("again"))
    log.end()
    text = file.getvalue()
    assert len(text.encode("utf-8")) < 3300
    assert text.count("the log is full for this run") == 1
    assert text.rstrip().endswith("the window ended")


def test_a_log_past_its_limit_is_kept_aside_and_a_new_one_begun(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Grown by errors before a crash, it is the log that explains it: a start of
    # the window again keeps it for the report.
    path = tmp_path / "window.log"
    path.write_text("an old run\n", encoding="utf-8")
    assert (
        window_log.start(path, "1.0.0", enable=lambda file: None, disable=lambda: None)
        is not None
    )
    assert "an old run" in path.read_text(encoding="utf-8")  # under the limit: kept
    monkeypatch.setattr(window_log, "LIMIT_BYTES", 10)
    assert (
        window_log.start(path, "1.0.1", enable=lambda file: None, disable=lambda: None)
        is not None
    )
    text = path.read_text(encoding="utf-8")
    assert "an old run" not in text
    assert "PhotoFinish 1.0.1 started" in text
    aside = (tmp_path / "window.log.1").read_text(encoding="utf-8")
    assert "an old run" in aside
    assert "PhotoFinish 1.0.0 started" in aside


def test_a_log_that_cannot_be_set_aside_is_written_on(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "window.log"
    path.write_text("an old run\n", encoding="utf-8")
    monkeypatch.setattr(window_log, "LIMIT_BYTES", 5)

    def busy(self: Path, target: Path) -> Path:
        raise PermissionError("open in another window")  # as Windows says

    monkeypatch.setattr(Path, "replace", busy)
    assert (
        window_log.start(path, "1.0.1", enable=lambda file: None, disable=lambda: None)
        is not None
    )
    text = path.read_text(encoding="utf-8")
    assert "an old run" in text
    assert "PhotoFinish 1.0.1 started" in text


def test_a_log_that_cannot_be_opened_leaves_the_window_to_start(
    tmp_path: Path, hooks: list[object]
) -> None:
    before = sys.excepthook
    (tmp_path / "data").write_text("a file where its folder would be")
    started = window_log.start(
        tmp_path / "data" / "window.log",
        "1.0.0",
        enable=lambda file: None,
        disable=lambda: None,
    )
    assert started is None
    assert sys.excepthook is before  # nothing hooked to a log that is not there


def test_a_line_that_cannot_be_written_is_let_go() -> None:
    file = io.StringIO()
    log = window_log.WindowLog(file)
    file.close()
    log.write("the disk full")  # no error out of the log into the window
    log.error(*raised("lost"))


def test_an_error_with_no_traceback_is_known_by_its_kind() -> None:
    file = io.StringIO()
    log = window_log.WindowLog(file)
    log.error(RuntimeError, RuntimeError("handed on bare"), None)
    log.error(RuntimeError, RuntimeError("handed on bare"), None)
    log.end()
    text = file.getvalue()
    assert text.count("RuntimeError: handed on bare") == 1
    assert "RuntimeError came 1 time more in its minute" in text


def test_a_clock_set_back_does_not_hold_an_error_back() -> None:
    # The referee sets the laptop's clock back an hour to the chronometer's: an
    # error's minute is a minute of the steady clock, not an hour more.
    file = io.StringIO()
    wall, steady = [50_400.0], [0.0]
    log = window_log.WindowLog(file, clock=lambda: wall[0], steady=lambda: steady[0])
    log.error(*raised("again"))
    wall[0], steady[0] = 46_861.0, 61.0  # an hour back, a minute on
    log.error(*raised("again"))
    assert file.getvalue().count("ValueError: again") == 2


def test_an_error_repeating_till_a_crash_has_its_count_written_as_it_grows() -> None:
    # A paint failing at every frame till Qt crashes: the minute's count is never
    # said at its end, so it is written on the way -- at the first repeat, then
    # every 5 s: a crash leaves it at most 5 s short.
    file = io.StringIO()
    now = [1000.0]
    log = window_log.WindowLog(file, clock=lambda: now[0], steady=lambda: now[0])
    for frame in range(150):
        now[0] = 1000.0 + frame * 0.125
        log.error(*raised("at every frame"))
    text = file.getvalue()  # no end: the crash
    assert text.count("ValueError: at every frame") == 1
    for count in ("1 time", "41 times", "81 times", "121 times"):
        assert f"came {count} more so far" in text
    assert text.count("so far") == 4


class _FailingAtItsEnd:
    def __del__(self) -> None:
        raise RuntimeError("in a finalizer")


def test_an_error_in_a_finalizer_goes_to_the_log(
    tmp_path: Path, hooks: list[object]
) -> None:
    # Python hands it to sys.unraisablehook, which prints to a stderr a window
    # started from Finder or Explorer does not have.
    path = tmp_path / "window.log"
    assert (
        window_log.start(path, "1.0.0", enable=lambda file: None, disable=lambda: None)
        is not None
    )
    _FailingAtItsEnd()  # dropped at once
    text = path.read_text(encoding="utf-8")
    assert "RuntimeError: in a finalizer" in text
    assert "_FailingAtItsEnd.__del__" in text  # whose: what Python says with it
    assert hooks == [RuntimeError]


def test_an_error_raised_while_the_log_writes_does_not_hang_the_window() -> None:
    # A finalizer raising while the log writes -- the collector runs it there --
    # comes back into the log on the same thread: it waited on its own lock for
    # ever, and the window with it.
    class Reentered(io.StringIO):
        def write(self, text: str) -> int:
            if "first" in text:
                log.error(*raised_elsewhere("from a finalizer"))
            return super().write(text)

    file = Reentered()
    log = window_log.WindowLog(file)
    writer = threading.Thread(target=log.error, args=raised("first"), daemon=True)
    writer.start()
    writer.join(timeout=5)
    assert not writer.is_alive()
    assert "ValueError: first" in file.getvalue()
    assert "KeyError: 'from a finalizer'" in file.getvalue()  # written too


def test_a_failure_of_the_log_itself_still_hands_each_error_on(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Its traceback too deep to format, say: the error still reaches the hook
    # before the log's, and nothing of the log's own escapes into the window.
    path = tmp_path / "window.log"
    assert (
        window_log.start(path, "1.0.0", enable=lambda file: None, disable=lambda: None)
        is not None
    )

    def broken(*args: object) -> None:
        raise RecursionError("too deep a chain")

    monkeypatch.setattr(window_log.WindowLog, "error", broken)
    sys.excepthook(*raised("in a slot"))
    thread = threading.Thread(target=lambda: 1 / 0)
    thread.start()
    thread.join()
    _FailingAtItsEnd()  # dropped at once
    assert hooks == [ValueError, ZeroDivisionError, RuntimeError]


def _fail(text: str) -> None:
    raise ValueError(text)  # the line both ways reach: a library's, say


def through(way: int) -> Raised:
    try:
        if way == 1:
            _fail("one way")
        else:
            _fail("another way")
    except ValueError as error:
        return type(error), error, error.__traceback__
    raise AssertionError("_fail raises")


def test_errors_raised_at_one_line_by_two_ways_are_two_errors() -> None:
    # Two bugs handing bad input to one library function: one line raises both,
    # each come its own way -- the second is no repeat of the first.
    file = io.StringIO()
    log = window_log.WindowLog(file)
    log.error(*through(1))
    log.error(*through(2))
    log.error(*through(2))
    text = file.getvalue()
    assert "ValueError: one way" in text
    assert "ValueError: another way" in text
    assert text.count("came 1 time more so far") == 1  # the other way, again


def test_errors_with_no_traceback_said_of_two_objects_are_two_errors() -> None:
    # A destructor's in native code: no traceback to tell them apart by, the
    # object Python names with each does.
    file = io.StringIO()
    log = window_log.WindowLog(file)
    error = RuntimeError("closing")
    log.error(RuntimeError, error, None, "Exception ignored in: <a decoder>")
    log.error(RuntimeError, error, None, "Exception ignored in: <a recorder>")
    text = file.getvalue()
    assert "Exception ignored in: <a decoder>" in text
    assert "Exception ignored in: <a recorder>" in text
    assert text.count("RuntimeError: closing") == 2


def test_an_object_python_names_with_an_error_is_in_the_log(
    tmp_path: Path, hooks: list[object]
) -> None:
    # A native extension names the object it could not finish, no words of its own.
    path = tmp_path / "window.log"
    assert (
        window_log.start(path, "1.0.0", enable=lambda file: None, disable=lambda: None)
        is not None
    )

    class Decoder:
        def __repr__(self) -> str:  # as long as a real object's
            return "<app.decoder.FrameDecoder of cam2 at 0x102c64bf0>"

    said = SimpleNamespace(
        exc_type=RuntimeError,
        exc_value=RuntimeError("closing"),
        exc_traceback=None,
        err_msg=None,
        object=Decoder(),
    )
    sys.unraisablehook(said)  # type: ignore[arg-type]
    text = path.read_text(encoding="utf-8")
    assert "Exception ignored in: <app.decoder.FrameDecoder of cam2 at 0x" in text
    assert hooks == [RuntimeError]


def test_a_finalizer_failing_for_each_new_object_is_counted_as_one_error() -> None:
    # Generators failing at their end, one a frame: one way, each object at an
    # address of its own -- written once, then counted, the run's room kept.
    file = io.StringIO()
    log = window_log.WindowLog(file)
    for k in range(5):
        said = f"Exception ignored while finalizing <generator frames at 0x{k:x}0>"
        log.error(*raised("closing"), said)
        log.error(RuntimeError, RuntimeError("bare"), None, said)
    text = file.getvalue()
    assert text.count("ValueError: closing") == 1
    assert text.count("RuntimeError: bare") == 1  # no traceback: known by whose


def test_an_object_of_any_kind_is_named_whole_up_to_its_limit(
    tmp_path: Path, hooks: list[object]
) -> None:
    # A string or a tuple named with an error: reprlib cut them to 30 characters
    # or 6 items whatever its limit for other objects.
    path = tmp_path / "window.log"
    assert (
        window_log.start(path, "1.0.0", enable=lambda file: None, disable=lambda: None)
        is not None
    )

    class Unnamable:
        def __repr__(self) -> str:
            raise RuntimeError("no name")

    things = ("a stream path of cam2 that runs long", tuple(range(12)), Unnamable())
    for thing in (*things, "x" * 1000):
        said = SimpleNamespace(
            exc_type=RuntimeError,
            exc_value=RuntimeError("closing"),
            exc_traceback=None,
            err_msg=None,
            object=thing,
        )
        sys.unraisablehook(said)  # type: ignore[arg-type]
    text = path.read_text(encoding="utf-8")
    assert "'a stream path of cam2 that runs long'" in text
    assert "(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)" in text
    assert "Unnamable" in text  # its repr failing: named by its kind
    assert f"'{'x' * 296}..." in text  # past its limit: cut there
    assert "x" * 400 not in text


def test_a_log_full_for_its_run_writes_no_error_after_saying_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(window_log, "LIMIT_BYTES", 1500)
    file = io.StringIO()
    now = [1000.0]
    log = window_log.WindowLog(file, clock=lambda: now[0], steady=lambda: now[0])
    log.error(*raised("small"))
    now[0] += 61
    log.error(*raised("x" * 2000))  # past the room left: the log says it is full
    now[0] += 61
    log.error(*raised_elsewhere("small again"))  # would fit: written no more
    log.end()
    text = file.getvalue()
    assert "the log is full for this run" in text
    assert "small again" not in text
    assert text.rstrip().endswith("the window ended")


def test_an_error_after_the_window_ended_is_said_to_be_at_its_exit() -> None:
    # A finalizer failing as Python ends, past "the window ended": not a crash
    # after a clean end, and the log says which.
    file = io.StringIO()
    log = window_log.WindowLog(file)
    log.end()
    log.error(*raised("tearing down"))
    text = file.getvalue()
    assert "an error at the window's exit, after its end:" in text
    assert "an error no handler took:" not in text


def test_an_error_raised_inside_the_file_s_own_write_is_written_after_it() -> None:
    # A real file's buffered layer refuses a write from inside its own write --
    # "reentrant call": a finalizer's error raised there waits for the write
    # under way to end, and is written then.
    class Buffered(io.StringIO):
        writing = False

        def write(self, text: str) -> int:
            if self.writing:
                raise RuntimeError("reentrant call inside <_io.BufferedWriter>")
            self.writing = True
            try:
                if "first" in text:
                    log.error(*raised_elsewhere("from a finalizer"))
                return super().write(text)
            finally:
                self.writing = False

    file = Buffered()
    log = window_log.WindowLog(file)
    log.error(*raised("first"))
    text = file.getvalue()
    assert "ValueError: first" in text
    assert "KeyError: 'from a finalizer'" in text


def test_stacks_written_past_twice_the_room_turn_the_crash_stacks_off(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    # faulthandler writes outside the log's room -- on Windows also for an
    # exception native code handles itself, a frame each, say: the run's log
    # grown by twice the room, it is turned off, and that is said.
    monkeypatch.setattr(window_log, "WATCH_S", 0.01)
    monkeypatch.setattr(window_log, "LIMIT_BYTES", 100)
    path = tmp_path / "window.log"
    turned_off: list[bool] = []
    log = window_log.start(
        path, "1.0.0", enable=lambda file: None, disable=lambda: turned_off.append(True)
    )
    assert log is not None
    log.file.write("Windows fatal exception: access violation\n" * 10)  # as it would
    log.file.flush()
    said = "a crash's stacks are no longer written"
    deadline = time.monotonic() + 5
    while said not in path.read_text(encoding="utf-8") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert said in path.read_text(encoding="utf-8")
    assert turned_off == [True]


def test_the_watch_on_the_log_s_size_ends_with_its_file(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window_log, "WATCH_S", 0.01)
    before = set(threading.enumerate())
    log = window_log.start(
        tmp_path / "window.log",
        "1.0.0",
        enable=lambda file: None,
        disable=lambda: None,
    )
    assert log is not None
    (watch,) = set(threading.enumerate()) - before
    log.file.close()
    watch.join(timeout=5)
    assert not watch.is_alive()


def test_the_same_error_come_back_while_it_is_written_is_counted_once() -> None:
    # The collector runs a finalizer failing the same way inside the write of
    # that error: its traceback was written twice, its count begun again.
    class Reentered(io.StringIO):
        again = False

        def write(self, text: str) -> int:
            if "ValueError: first" in text and not self.again:
                self.again = True
                log.error(*raised("first"))
            return super().write(text)

    file = Reentered()
    log = window_log.WindowLog(file)
    log.error(*raised("first"))
    text = file.getvalue()
    assert text.count("ValueError: first") == 1
    assert "came 1 time more so far" in text


def test_a_log_whose_crash_stacks_cannot_be_kept_still_lets_the_window_start(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    # faulthandler refusing the file, or no thread left to watch it: the window
    # starts all the same, the stacks off, and the log says why.
    path = tmp_path / "window.log"
    turned_off: list[bool] = []

    def refused(file: object) -> None:
        raise RuntimeError("no such descriptor")

    log = window_log.start(
        path, "1.0.0", enable=refused, disable=lambda: turned_off.append(True)
    )
    assert log is not None
    said = "a crash's stacks are not written this run: RuntimeError: no such descriptor"
    assert said in path.read_text(encoding="utf-8")

    def no_thread(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", no_thread)
    log = window_log.start(
        path, "1.0.1", enable=lambda file: None, disable=lambda: turned_off.append(True)
    )
    assert log is not None
    assert "can't start new thread" in path.read_text(encoding="utf-8")
    assert turned_off == [True, True]


def test_the_log_s_lines_end_as_its_room_counts_them(
    tmp_path: Path, hooks: list[object]
) -> None:
    # Windows' text mode wrote "\r\n" for each "\n" the room counted: past its
    # 5 MB by a few percent there. The lines end in "\n" on every system.
    path = tmp_path / "window.log"
    log = window_log.start(
        path, "1.0.0", enable=lambda file: None, disable=lambda: None
    )
    assert log is not None
    log.error(*raised("two\nlines"))
    log.end()
    data = path.read_bytes()
    assert b"\r\n" not in data
    assert data.count(b"\n") >= 6


def test_qt_objects_failing_at_their_end_are_one_error_whatever_their_pointers() -> (
    None
):
    # PySide names a C++ object's pointer in brackets besides where its Python
    # side lives: each new widget's finalizer error was a new error, the room
    # used up by them.
    file = io.StringIO()
    log = window_log.WindowLog(file)
    for k in range(5):
        said = (
            "Exception ignored in: "
            f"<PySide6.QtCore.QObject(0x79d00{k}4500) at 0x10649{k}100>"
        )
        log.error(RuntimeError, RuntimeError("bare"), None, said)
    assert file.getvalue().count("RuntimeError: bare") == 1


def test_the_same_error_come_back_while_it_is_formatted_is_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The collector runs a finalizer failing the same way while the traceback is
    # formatted, before the log has written anything of it.
    file = io.StringIO()
    log = window_log.WindowLog(file)
    real = window_log.traceback.format_exception
    first = [True]

    def formatting(*args: Any, **kwargs: Any) -> list[str]:
        if first:
            first.clear()
            log.error(*raised("first"))
        return real(*args, **kwargs)

    monkeypatch.setattr(window_log.traceback, "format_exception", formatting)
    log.error(*raised("first"))
    text = file.getvalue()
    assert text.count("ValueError: first") == 1
    assert "came 1 time more so far" in text


def test_a_minute_s_count_is_written_as_it_ends_not_at_the_next_error() -> None:
    # A burst that stops: its count waited for another error, maybe an hour on,
    # and was stamped then, reading as a second burst.
    file = io.StringIO()
    now = [1000.0]
    log = window_log.WindowLog(file, clock=lambda: now[0], steady=lambda: now[0])
    for second in range(10):
        now[0] = 1000.0 + second
        log.error(*raised("a burst"))
    now[0] = 1061.0
    log.tick()  # as the watch does, every WATCH_S
    assert "came 9 times more in its minute" in file.getvalue()


def test_the_watch_has_the_minutes_said_each_time_it_looks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(window_log, "WATCH_S", 0.0)
    ticks: list[int] = []
    stopped = threading.Event()

    def tick() -> None:
        ticks.append(1)
        stopped.set()  # the window's end

    log = SimpleNamespace(
        tick=tick, file=SimpleNamespace(closed=False), stopped=stopped
    )
    window_log._watch(log, None)  # type: ignore[arg-type]
    assert ticks == [1]


def test_the_watch_goes_on_having_minutes_said_after_the_stacks_are_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # It turned the stacks off and stopped: a burst's count waited again for the
    # next error, an hour on maybe.
    monkeypatch.setattr(window_log, "WATCH_S", 0.0)
    monkeypatch.setattr(window_log, "LIMIT_BYTES", 10)
    turned_off: list[bool] = []
    said: list[str] = []

    with (tmp_path / "grown.log").open("a") as file:

        class Log:
            def __init__(self) -> None:
                self.file = file
                self.ticks = 0
                self.stopped = threading.Event()

            def tick(self) -> None:
                self.ticks += 1
                if self.ticks == 1:  # stacks past the room: 2 x 10 bytes
                    file.write("Windows fatal exception: access violation\n")
                    file.flush()
                if self.ticks == 3:
                    file.close()  # the window gone: the watch ends

            def write(self, text: str) -> None:
                said.append(text)

        log = Log()
        window_log._watch(log, lambda: turned_off.append(True))  # type: ignore[arg-type]
    assert turned_off == [True]
    assert said == [
        "the log is full for this run: a crash's stacks are no longer written"
    ]
    assert log.ticks == 3  # on after the stacks were turned off


def test_the_watch_has_minutes_said_when_the_stacks_cannot_be_kept(
    tmp_path: Path, hooks: list[object]
) -> None:
    def refused(file: object) -> None:
        raise RuntimeError("no such descriptor")

    before = set(threading.enumerate())
    log = window_log.start(
        tmp_path / "window.log", "1.0.0", enable=refused, disable=lambda: None
    )
    assert log is not None
    assert [t.name for t in set(threading.enumerate()) - before] == [
        "the window log's size"
    ]


def test_the_watch_looks_at_the_log_every_second() -> None:
    # faulthandler writes between two looks unbounded: at every 10 s, a native
    # exception at each frame could put megabytes past the stacks' room.
    assert window_log.WATCH_S <= 1.0


def test_a_count_names_no_object_of_the_first_error_when_others_came() -> None:
    # Two objects' finalizers failing on one line come one way, counted together:
    # the count names their kind and line, not the first one's object.
    file = io.StringIO()
    log = window_log.WindowLog(file)
    log.error(*raised("closing"), "Exception ignored in: <Decoder A>")
    log.error(*raised("closing"), "Exception ignored in: <SoundPlayer B>")
    counts = [line for line in file.getvalue().splitlines() if "so far" in line]
    assert len(counts) == 1
    assert "<Decoder A>" not in counts[0]


def test_the_end_stops_the_watch_and_no_error_after_it_waits_for_ever(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python freezes a daemon thread at its exit wherever it is: the watch frozen
    # with the log's lock held, an error at teardown waited on it for ever, and
    # the window's process never ended.
    monkeypatch.setattr(window_log, "WATCH_S", 0.01)
    log = window_log.start(
        tmp_path / "window.log", "1.0.0", enable=lambda file: None, disable=lambda: None
    )
    assert log is not None
    watch = log.watch
    assert watch is not None
    log.end()
    assert not watch.is_alive()
    taken, freed = threading.Event(), threading.Event()

    def frozen() -> None:  # a thread holding the lock, as one Python froze would
        with log._lock:
            taken.set()
            freed.wait()

    threading.Thread(target=frozen, daemon=True).start()
    taken.wait()
    began = time.monotonic()
    log.error(*raised("at teardown"))
    assert time.monotonic() - began < 5
    freed.set()


def test_the_watch_starts_when_the_log_s_size_cannot_be_had(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The file's size not to be had at the start: no watch was started at all,
    # and a burst's count waited for the next error again. The stacks, with no
    # room to keep, are off.
    def no_size(*args: object) -> None:
        raise OSError("not on this file system")

    # The log's own view of os: the test's machinery keeps the real one.
    monkeypatch.setattr(
        window_log, "os", SimpleNamespace(fstat=no_size, getpid=os.getpid)
    )
    path = tmp_path / "window.log"
    log = window_log.start(
        path, "1.0.0", enable=lambda file: None, disable=lambda: None
    )
    assert log is not None
    assert log.watch is not None
    deadline = time.monotonic() + 5
    said = "a crash's stacks are not written this run: OSError"
    while said not in path.read_text(encoding="utf-8") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert said in path.read_text(encoding="utf-8")
    assert log.watch.is_alive()  # on, to have the minutes said


def test_the_watch_ends_when_the_log_s_file_goes_while_it_looks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window_log, "WATCH_S", 0.0)
    with (tmp_path / "window.log").open("a") as real:

        class Going:
            closed = False  # closed between its look and its size
            calls = 0

            def fileno(self) -> int:
                self.calls += 1
                if self.calls > 1:
                    raise ValueError("I/O operation on closed file")
                return real.fileno()

        log = SimpleNamespace(
            tick=lambda: None,
            file=Going(),
            stopped=threading.Event(),
            write=lambda text: None,
        )
        window_log._watch(log, lambda: None)  # type: ignore[arg-type]
