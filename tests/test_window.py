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
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app import main_window as mw
from app import output_list, session
from app.lines import scale_time, to_line_scale
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


def journal(path: Path) -> list[dict[str, Any]]:
    text = path.with_name(path.name + ".journal.txt").read_text()
    return [json.loads(line) for line in text.splitlines()]


def choose(monkeypatch: pytest.MonkeyPatch, path: Path | str) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))


def test_enter_adds_a_crossing_at_the_frame_shown(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = recording / "results_video.txt"
    win = make_window()
    choose(monkeypatch, out)
    win.choose_output()
    assert session.load()["output"] == str(out)
    assert win.output_button.text() == f"Output: {out}"
    wait_until(showing(win, START + 69 * 33))
    win.step(-9)
    win.number.setText(" 15 ")
    QTest.keyClick(win.number, Qt.Key.Key_Return)
    moment = scale_time(to_line_scale(START + 60 * 33, False))
    assert out.read_text() == f"15#{moment}#nextLap#\n"
    assert win.number.text() == ""
    assert win.statusBar().currentMessage() == f"Added 15 at {moment}"
    (entry,) = journal(out)
    frame = win.cameras["cam1"].index.frame(60)
    assert entry["op"] == "add"
    assert entry["method"] == "frame"
    assert entry["camera"] == "cam1"
    assert entry["frames"] == [[frame.path.name, frame.pts, START + 60 * 33]]
    assert entry["offsets"] == {"camera_ms": 0, "source_ms": 0}
    win.finish.setChecked(True)
    assert session.load()["finish_mode"] is True
    win.number.setText("16")
    win.add_crossing()
    assert out.read_text().splitlines()[-1] == f"16#{moment}#finish#"


def test_the_keys_move_the_video_while_a_number_is_typed(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    win.show()
    win.activateWindow()
    wait_until(showing(win, START + 69 * 33))
    win.number.setFocus()
    QTest.keyClicks(win.number, "15")
    QTest.keyClick(win.number, Qt.Key.Key_Left)
    wait_until(showing(win, START + 68 * 33))
    QTest.keyClick(win.number, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    wait_until(showing(win, START + 58 * 33))
    QTest.keyClick(win.number, Qt.Key.Key_L)
    wait_until(showing(win, START + 69 * 33))
    assert win.number.text() == "15"
    QTest.keyClick(win.number, Qt.Key.Key_Backspace)
    assert win.number.text() == "1"


def test_a_crossing_needs_an_output_a_frame_and_a_number(
    make_window: Callable[[], mw.MainWindow],
    base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    win.add_crossing()
    assert win.statusBar().currentMessage() == "Choose the output file first"
    choose(monkeypatch, "")
    win.choose_output()
    assert win.output is None
    session.save({**session.DEFAULTS, "input": "results.txt"})
    win.session = session.load()
    choose(monkeypatch, base / "results.txt")
    win.choose_output()
    assert win.output is None
    assert "only read" in win.statusBar().currentMessage()
    choose(monkeypatch, "out.txt")
    win.choose_output()
    assert win.output is not None
    win.add_crossing()
    assert (
        win.statusBar().currentMessage() == "There is no frame to time the crossing on"
    )


def test_a_crossing_without_a_number_or_a_disk_is_refused(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    choose(monkeypatch, recording / "out.txt")
    win.choose_output()
    wait_until(lambda: win.place is not None)
    win.number.setText(" # ")
    win.add_crossing()
    assert win.statusBar().currentMessage() == "Type the rider's number first"

    def full(path: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(output_list, "_write_in_one_step", full)
    win.number.setText("15")
    win.add_crossing()
    assert "cannot be written: disk full" in win.statusBar().currentMessage()
    assert win.number.text() == "15"


def test_an_output_that_cannot_be_opened_is_said(
    base: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    (base / "a folder").mkdir()
    session.save({**session.DEFAULTS, "output": "a folder"})
    win = make_window()
    assert win.output is None
    assert "cannot be opened" in win.statusBar().currentMessage()
