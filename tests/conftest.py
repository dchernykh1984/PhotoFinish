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

from PySide6.QtCore import QProcess
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


class Analyzer:
    """An analyser process that would be running, until its input is closed."""

    def __init__(self, camera_id: str) -> None:
        self.camera_id, self.running = camera_id, True

    def state(self) -> QProcess.ProcessState:
        if self.running:
            return QProcess.ProcessState.Running
        return QProcess.ProcessState.NotRunning

    def closeWriteChannel(self) -> None:  # noqa: N802 - QProcess's name
        self.running = False

    def waitForFinished(self, ms: int) -> bool:  # noqa: N802 - QProcess's name
        return not self.running

    def kill(self) -> None:
        self.running = False


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
        made.append(mw.MainWindow())
        return made[-1]

    yield make
    for window in made:
        window.close()
        window.deleteLater()


@pytest.fixture
def win(make_window: Callable[[], mw.MainWindow]) -> mw.MainWindow:
    """A MainWindow under the offscreen platform, in a folder of its own."""
    return make_window()


def wait_until(condition: Callable[[], bool], seconds: float = 10) -> None:
    """Run Qt's events until ``condition`` holds."""
    until = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < until, "timed out"
        QApplication.processEvents()
        time.sleep(0.01)
