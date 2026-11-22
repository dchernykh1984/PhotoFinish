"""The window's log: its starts, the errors no handler took, a crash's stacks."""

from __future__ import annotations

import io
import sys
import threading
from pathlib import Path
from types import TracebackType

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
    log = window_log.start(path, "9.9.9", enable=enabled.append)
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
    assert window_log.start(path, "1.0.0", enable=lambda file: None) is not None
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
    assert window_log.start(path, "1.0.0", enable=lambda file: None) is not None
    assert "an old run" in path.read_text(encoding="utf-8")  # under the limit: kept
    monkeypatch.setattr(window_log, "LIMIT_BYTES", 10)
    assert window_log.start(path, "1.0.1", enable=lambda file: None) is not None
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
    assert window_log.start(path, "1.0.1", enable=lambda file: None) is not None
    text = path.read_text(encoding="utf-8")
    assert "an old run" in text
    assert "PhotoFinish 1.0.1 started" in text


def test_a_log_that_cannot_be_opened_leaves_the_window_to_start(
    tmp_path: Path, hooks: list[object]
) -> None:
    before = sys.excepthook
    (tmp_path / "data").write_text("a file where its folder would be")
    started = window_log.start(
        tmp_path / "data" / "window.log", "1.0.0", enable=lambda file: None
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
    # said at its end, so it is written on the way -- once, ten times, a hundred.
    file = io.StringIO()
    now = [1000.0]
    log = window_log.WindowLog(file, clock=lambda: now[0], steady=lambda: now[0])
    for frame in range(150):
        now[0] = 1000.0 + frame * 0.1
        log.error(*raised("at every frame"))
    text = file.getvalue()  # no end: the crash
    assert text.count("ValueError: at every frame") == 1
    assert "came 1 time more so far" in text
    assert "came 10 times more so far" in text
    assert "came 100 times more so far" in text
    assert text.count("so far") == 3


class _FailingAtItsEnd:
    def __del__(self) -> None:
        raise RuntimeError("in a finalizer")


def test_an_error_in_a_finalizer_goes_to_the_log(
    tmp_path: Path, hooks: list[object]
) -> None:
    # Python hands it to sys.unraisablehook, which prints to a stderr a window
    # started from Finder or Explorer does not have.
    path = tmp_path / "window.log"
    assert window_log.start(path, "1.0.0", enable=lambda file: None) is not None
    _FailingAtItsEnd()  # dropped at once
    assert "RuntimeError: in a finalizer" in path.read_text(encoding="utf-8")
    assert hooks == [RuntimeError]
