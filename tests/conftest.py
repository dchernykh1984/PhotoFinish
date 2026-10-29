"""Shared Qt fixtures for the window tests.

main_window is excluded from coverage, so these Qt-level tests are what keeps its
handlers from drifting silently. Every window runs in a folder of its own and starts
no recorder: ``spawned`` lists the cameras it would have started.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QProcess
from PySide6.QtWidgets import QApplication

from app import main_window as mw
from app import paths
from app.recorder import launcher

_app = QApplication.instance() or QApplication([])


class _Process:
    """A recorder that would be running."""

    def poll(self) -> int | None:
        return None


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder the program keeps its data in, for this test."""
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def spawn(camera_id: str) -> _Process:
        calls.append(camera_id)
        return _Process()

    monkeypatch.setattr(launcher, "spawn", spawn)
    return calls


class Analyzer(QObject):
    """An analyser process that would be running, until its input is closed; one
    ``slow`` still on its segment, until it is killed."""

    def __init__(self, camera_id: str) -> None:
        super().__init__()
        self.camera_id, self.running, self.slow, self.killed = (
            camera_id,
            True,
            False,
            False,
        )

    def state(self) -> QProcess.ProcessState:
        if self.running:
            return QProcess.ProcessState.Running
        return QProcess.ProcessState.NotRunning

    def closeWriteChannel(self) -> None:  # noqa: N802 - QProcess's name
        self.running = self.running and self.slow

    def kill(self) -> None:
        self.running, self.killed = False, True


@pytest.fixture
def analyzers(monkeypatch: pytest.MonkeyPatch) -> list[Analyzer]:
    """The analysers the window starts, none of them a process."""
    started: list[Analyzer] = []

    def start(camera_id: str, parent: object) -> Analyzer:
        started.append(Analyzer(camera_id))
        return started[-1]

    monkeypatch.setattr(mw, "start_analyzer", start)
    return started


@pytest.fixture
def make_window(
    base: Path, spawned: list[str], analyzers: list[Analyzer]
) -> Iterator[Callable[[], mw.MainWindow]]:
    made: list[mw.MainWindow] = []

    def make() -> mw.MainWindow:
        window = mw.MainWindow()
        # As a referee does, the tests look at a frame once it is on screen: the
        # window refuses to time on a picture still on its way.
        for name in MOVES:
            setattr(window, name, _settling(window, getattr(window, name)))
        settled(window)
        made.append(window)
        return window

    yield make
    for window in made:
        window.close()
        window.deleteLater()


@pytest.fixture
def win(make_window: Callable[[], mw.MainWindow]) -> mw.MainWindow:
    """A MainWindow under the offscreen platform, in a folder of its own."""
    return make_window()


MOVES = (
    "step",
    "step_ms",
    "seek_ms",
    "seek_line",
    "go_live",
    "next_rider",
    "previous_rider",
    "poll",
)


def settled(window: mw.MainWindow) -> None:
    """Every camera's frame on screen, none on its way."""
    wait_until(lambda: not any(c.view.waiting for c in window.cameras.values()))


def _settling(
    window: mw.MainWindow, move: Callable[..., object]
) -> Callable[..., object]:
    def moved(*args: object, **kwargs: object) -> object:
        done = move(*args, **kwargs)
        settled(window)
        return done

    return moved


def wait_until(condition: Callable[[], bool], seconds: float = 10) -> None:
    """Run Qt's events until ``condition`` holds."""
    until = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < until, "timed out"
        QApplication.processEvents()
        time.sleep(0.01)
