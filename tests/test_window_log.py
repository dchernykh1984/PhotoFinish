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


@pytest.fixture
def hooks(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """The hooks before the log's: what they were called with; put back after."""
    called: list[object] = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: called.append(error[0]))
    monkeypatch.setattr(threading, "excepthook", lambda a: called.append(a.exc_type))
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


def test_the_same_error_again_within_a_minute_is_counted_not_written() -> None:
    file = io.StringIO()
    now = [1000.0]
    log = window_log.WindowLog(file, clock=lambda: now[0])
    error = raised("each second")
    for second in range(62):
        now[0] = 1000.0 + second
        log.error(*error)
    log.error(*raised("another"))
    log.error(*error)  # after another: written again
    log.end()
    text = file.getvalue()
    assert text.count("ValueError: each second") == 3  # at 0 s, 60 s, after another
    assert "the error before came 59 times more" in text
    assert "the error before came 1 time more" in text  # at 61 s, said before another
    assert text.count("ValueError: another") == 1


def test_a_log_past_its_limit_starts_over(
    tmp_path: Path, hooks: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "window.log"
    path.write_text("an old run\n", encoding="utf-8")
    assert window_log.start(path, "1.0.0", enable=lambda file: None) is not None
    assert "an old run" in path.read_text(encoding="utf-8")  # under the limit: kept
    monkeypatch.setattr(window_log, "LIMIT_BYTES", 10)
    assert window_log.start(path, "1.0.1", enable=lambda file: None) is not None
    text = path.read_text(encoding="utf-8")
    assert "an old run" not in text
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
