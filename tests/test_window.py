"""The window: cameras, the video, moving through it."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app import main_window as mw
from app import session
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import read_time, render
from app.widgets.camera_dialog import CameraDialog
from tests.conftest import wait_until

START = 1_761_716_129_587
CAMERA = {"id": "cam1", "name": "Side", "connection": "test", "settings": {"fps": 30}}


def record(base: Path, start: int, frames: int, camera_id: str = "cam1") -> None:
    writer = SegmentWriter(base / "video" / camera_id, fps=30)
    for k in range(frames):
        writer.write(render(start + k * 33, 640, 360), start + k * 33)
    writer.close()


def beating(base: Path, camera_id: str = "cam1", **info: Any) -> None:
    """A recorder that is running, as its heartbeat says."""
    folder = base / "video" / camera_id
    folder.mkdir(parents=True, exist_ok=True)
    beat = {"state": "recording", "frames": 70, "detail": ""} | info
    beat["heartbeat_ms"] = time.time_ns() // 1_000_000
    (folder / "recorder.json").write_text(json.dumps(beat))


def shown(win: mw.MainWindow) -> int:
    """The moment the frame on screen shows, read from its pixels."""
    image = win.view.image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = image.width(), image.height()
    pixels = np.frombuffer(image.constBits(), np.uint8)
    rows = pixels.reshape(height, image.bytesPerLine())[:, : width * 3]
    return read_time(rows.reshape(height, width, 3))


def showing(win: mw.MainWindow, ms: int) -> Callable[[], bool]:
    return lambda: not win.view.image.isNull() and shown(win) == ms


def test_window_title_names_the_app(win: mw.MainWindow) -> None:
    assert win.windowTitle() == "PhotoFinish"
    assert win.view.text == "Add a camera"


@pytest.fixture
def recording(base: Path) -> Path:
    session.save({**session.DEFAULTS, "cameras": [CAMERA]})
    record(base, START, 70)
    beating(base)
    return base


def test_the_newest_frame_is_shown_and_followed(
    recording: Path, make_window: Callable[[], mw.MainWindow], spawned: list[str]
) -> None:
    win = make_window()
    assert spawned == []  # its recorder is running: attached, not started
    wait_until(showing(win, START + 69 * 33))
    assert win.time_label.text().endswith("LIVE")
    assert win.camera_list.item(0).text() == "Side: recording, 70 frames"
    record(recording, START + 5000, 10)
    win.poll()
    wait_until(showing(win, START + 5000 + 9 * 33))
    assert win.timeline.gaps == [(START + 69 * 33, START + 5000)]


def test_stepping_moves_by_frames_and_by_seconds(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-1)
    wait_until(showing(win, START + 68 * 33))
    assert not win.time_label.text().endswith("LIVE")
    win.step(-10)
    wait_until(showing(win, START + 58 * 33))
    win.step_ms(-1000)
    wait_until(showing(win, START + 28 * 33))
    win.step(-100)
    wait_until(showing(win, START))
    win.step_ms(1000)
    wait_until(showing(win, START + 30 * 33))
    win.go_live()
    wait_until(showing(win, START + 69 * 33))


def test_the_keys_step_and_go_live(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    win.show()
    win.activateWindow()
    wait_until(showing(win, START + 69 * 33))
    for key, modifier, place in (
        (Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier, 68),
        (Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier, 58),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier, 59),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier, 69),
        (Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier, 39),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier, 69),
        (Qt.Key.Key_Home, Qt.KeyboardModifier.NoModifier, 69),
    ):
        QTest.keyClick(win, key, modifier)
        wait_until(showing(win, START + place * 33))
    win.step(-5)
    QTest.keyClick(win, Qt.Key.Key_L)
    wait_until(showing(win, START + 69 * 33))


def test_a_click_on_the_timeline_moves_the_video_there(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    win.resize(1000, 600)
    wait_until(showing(win, START + 69 * 33))
    x = win.timeline.x_at(START + 20 * 33)
    QTest.mouseClick(
        win.timeline, Qt.MouseButton.LeftButton, pos=QPointF(x, 20).toPoint()
    )
    wait_until(showing(win, START + 20 * 33))
    assert not win.live


def test_a_camera_added_is_saved_and_its_recorder_started(
    win: mw.MainWindow, spawned: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        CameraDialog, "exec", lambda self: CameraDialog.DialogCode.Accepted
    )
    win.add_camera()
    (camera,) = session.load()["cameras"]
    assert (camera["id"], camera["connection"], camera["record"]) == (
        "cam1",
        "test",
        True,
    )
    assert spawned == ["cam1"]
    assert win.camera_list.item(0).text() == "Camera 1: starting"
    assert win.view.text == "No video yet"
    monkeypatch.setattr(
        CameraDialog, "exec", lambda self: CameraDialog.DialogCode.Rejected
    )
    win.add_camera()
    assert len(session.load()["cameras"]) == 1


def test_a_removed_camera_stops_recording_and_keeps_its_video(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answers.pop(0))
    win.remove_camera()
    assert session.load()["cameras"] == [CAMERA]
    win.remove_camera()
    assert session.load()["cameras"] == []
    folder = recording / "video" / "cam1"
    assert (folder / "stop.request").exists()
    assert list(folder.glob("*-*-*.mkv"))
    assert win.camera_list.count() == 0
    assert win.view.text == "Add a camera"
    win.remove_camera()  # nothing chosen: nothing happens
    assert win._free_id() == "cam2"  # cam1's recording is still on disk


def test_the_list_says_how_each_recorder_is(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    beating(recording, detail="low disk")
    win.poll()
    assert (
        win.camera_list.item(0).text() == "Side: recording, 70 frames, under 2 GB free"
    )
    beating(recording, state="disk_full")
    win.poll()
    assert win.camera_list.item(0).text() == "Side: disk full, recording stopped"
