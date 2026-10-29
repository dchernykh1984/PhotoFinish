"""The window's widgets on their own."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from app.recorder.segments import SegmentWriter
from app.recorder.testcam import render
from app.widgets.camera_dialog import CameraDialog
from app.widgets.camera_view import CameraView
from app.widgets.decode_worker import DecodeWorker
from app.widgets.timeline import LEAST_VIEW_MS, Timeline
from tests.conftest import wait_until

START = 1_761_716_129_587


def test_the_dialog_fills_a_preset_in_and_says_untested() -> None:
    dialog = CameraDialog(None, "cam3", ["FaceTime HD Camera", "PC Camera"])
    labels = [dialog.preset.itemText(i) for i in range(dialog.preset.count())]
    assert labels[0] == "None"
    assert all(label.endswith("(untested)") for label in labels[1:])
    dialog.preset.setCurrentIndex(1)
    camera = dialog.camera()
    assert camera["connection"] == "usb"
    assert camera["settings"] == {
        "device": "PC Camera",
        "width": 1280,
        "height": 720,
        "fps": 30,
    }
    assert camera["preset"] == "sjcam-hd1080p-usb"
    assert camera["name"] == "SJCAM HD1080P over USB"
    dialog.preset.setCurrentIndex(2)
    assert dialog.camera()["settings"] == {
        "url": "rtsp://192.168.1.254/sjcam.mov",
        "transport": "tcp",
    }
    dialog.preset.setCurrentIndex(3)
    assert dialog.camera()["settings"] == {"port": 1935, "path": "live/sj10pro"}
    assert dialog.address.text().endswith(":1935/live/sj10pro")
    dialog.preset.setCurrentIndex(0)  # back to none: the fields stay
    assert dialog.kind() == "rtmp"


def test_the_dialog_keeps_ok_off_while_the_camera_cannot_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = CameraDialog(None, "cam1", [])
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    assert dialog.camera()["name"] == "Camera 1"
    assert dialog.camera()["settings"]["scene"] == "bar"
    assert ok.isEnabled()
    dialog.connection.setCurrentIndex(0)  # USB, no camera named
    assert not ok.isEnabled()
    assert "name is missing" in dialog.problems.text()
    dialog.connection.setCurrentIndex(2)  # RTMP
    dialog.path.setText("/bad")
    assert dialog.address.text() == ""
    assert not ok.isEnabled()
    dialog.connection.setCurrentIndex(4)  # a file
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args: ("/videos/race.mp4", "")
    )
    dialog._choose_file()
    assert dialog.camera()["settings"] == {"path": "/videos/race.mp4"}
    assert ok.isEnabled()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    dialog._choose_file()
    assert dialog.file.text() == "/videos/race.mp4"
    dialog.name.setText("  ")
    assert dialog.camera()["name"] == "cam1"


def test_the_view_fits_the_frame_and_says_when_there_is_none() -> None:
    view = CameraView()
    view.resize(400, 400)
    assert view.image_rect().isNull()
    view.grab()
    view.show_image(QImage(160, 90, QImage.Format.Format_RGB888))
    rect = view.image_rect()
    assert (rect.width(), rect.height(), rect.top()) == (400, 225, 87.5)
    view.grab()
    view.show_text("Waiting")
    assert view.image.isNull()
    assert view.text == "Waiting"


def recording(timeline: Timeline, frames: int = 300) -> np.ndarray:
    moments = START + np.arange(frames, dtype=np.int64) * 33
    timeline.set_recording(moments, [(START + 1000, START + 2000)])
    return moments


def test_the_timeline_zooms_around_the_pointer_and_ticks_frames() -> None:
    timeline = Timeline()
    timeline.resize(1000, 48)
    moments = recording(timeline)
    assert timeline.view == (START, int(moments[-1]))
    middle = START + 4000
    x = timeline.x_at(middle)
    timeline.zoom(0.1, x)
    assert timeline.zoomed
    assert abs(timeline.ms_at(x) - middle) <= 1
    assert timeline.view[1] - timeline.view[0] == round((moments[-1] - START) * 0.1)
    timeline.set_position(middle)
    timeline.grab()  # frames ticked, the position marked
    timeline.zoom(0.0001, x)
    assert timeline.view[1] - timeline.view[0] == LEAST_VIEW_MS
    timeline.zoom(1e6, x)
    assert not timeline.zoomed
    assert timeline.view == (START, int(moments[-1]))


def test_a_zoomed_timeline_follows_the_newest_frame_when_live() -> None:
    timeline = Timeline()
    timeline.resize(1000, 48)
    recording(timeline, 300)
    timeline.zoom(0.5, 500)
    length = timeline.view[1] - timeline.view[0]
    moments = recording(timeline, 600)
    assert timeline.view == (int(moments[-1]) - length, int(moments[-1]))
    timeline.following = False
    before = timeline.view
    recording(timeline, 900)
    assert timeline.view == before


def test_the_wheel_zooms_and_a_click_seeks() -> None:
    timeline = Timeline()
    timeline.resize(1000, 48)
    recording(timeline)
    asked: list[int] = []
    timeline.seek.connect(asked.append)
    wheel = QWheelEvent(
        QPointF(500, 20),
        QPointF(500, 20),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(timeline, wheel)
    assert timeline.zoomed
    flat = QWheelEvent(
        QPointF(500, 20),
        QPointF(500, 20),
        QPoint(0, 0),
        QPoint(0, 0),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    view = timeline.view
    QApplication.sendEvent(timeline, flat)
    assert timeline.view == view
    QTest.mouseClick(timeline, Qt.MouseButton.RightButton, pos=QPoint(100, 20))
    assert asked == []
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(500, 20))
    assert asked == [timeline.ms_at(500)]


def test_the_newest_request_is_decoded_and_a_bad_one_answered(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    for k in range(10):
        writer.write(render(START + k * 33, 640, 360), START + k * 33)
    writer.close()
    (segment,) = tmp_path.glob("*-*-*.mkv")
    worker = DecodeWorker()
    answers: list[tuple[object, bool]] = []
    worker.decoded.connect(lambda tag, image: answers.append((tag, image.isNull())))
    for k in range(10):
        worker.request(segment, k * 33, k)
    wait_until(lambda: bool(answers) and answers[-1][0] == 9)
    assert answers[-1] == (9, False)
    worker.request(tmp_path / "missing.mkv", 0, "missing")
    wait_until(lambda: answers[-1][0] == "missing")
    assert answers[-1] == ("missing", True)
    worker.stop()


def test_rows_say_what_the_referee_must_notice() -> None:
    from app.input_follow import InputLine
    from app.output_list import OutputLine
    from app.widgets.lists import input_rows, output_rows

    taken = "15#20389 11:35:29.615#nextLap#"
    rows = input_rows(
        [InputLine(taken), InputLine("15#20389 11:35:29.500#nextLap#", taken)]
    )
    assert (rows[0].time, rows[0].warn, rows[0].note) == ("11:35:29.615", False, "")
    assert rows[1].note == f"changed; taken as {taken}"
    lines = [
        OutputLine(taken, {"input": taken}, "input"),
        OutputLine(taken, {"input": taken}, "interpolated", removed_from_input=True),
        OutputLine("7##", {"outside": True}, "outside"),
        OutputLine("8", {"added": True}, "hand"),
    ]
    notes = [(row.note, row.warn, row.time) for row in output_rows(lines)]
    assert notes == [
        ("", False, "11:35:29.615"),
        ("between two frames; removed from input", True, "11:35:29.615"),
        ("no time; found in the file", True, ""),
        ("no time; picked by hand", True, ""),
    ]


def test_the_list_marks_the_line_nearest_the_video() -> None:
    from app.widgets.lists import LinesView, Row

    view = LinesView()
    view.resize(400, 300)
    rows = [Row(str(n), "", "", "", None if n == 2 else n * 1000) for n in range(5)]
    view.show_rows([Row("x", "", "", "note", None, True), *rows])
    model = view.lines
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Time"
    assert model.headerData(1, Qt.Orientation.Vertical) is None
    view.follow(2900)
    assert model.near == 4
    index = model.index(4, 0)
    assert model.data(index) == "3"
    assert model.data(index, Qt.ItemDataRole.BackgroundRole) is not None
    font = model.data(index, Qt.ItemDataRole.FontRole)
    assert isinstance(font, QFont)
    assert font.bold()
    assert model.data(model.index(0, 3), Qt.ItemDataRole.ToolTipRole) == "note"
    assert model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole) is not None
    assert model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole) is None
    assert model.data(model.index(1, 0), Qt.ItemDataRole.ToolTipRole) is None
    assert model.data(model.index(1, 0), Qt.ItemDataRole.EditRole) is None
    view.follow(2950)
    assert model.near == 4
    picked: list[int] = []
    view.picked.connect(picked.append)
    view._pick(model.index(0, 0))
    view._pick(model.index(2, 0))
    assert picked == [1000]
    view.show_rows([])
    view.follow(0)
    assert model.near is None
    assert model.rowCount(model.index(0, 0)) == 0


def test_a_click_on_the_picture_is_told_in_picture_coordinates() -> None:
    view = CameraView()
    view.resize(400, 400)
    clicks: list[tuple[float, float]] = []
    view.clicked.connect(clicks.append)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert clicks == []  # no frame
    view.show_image(QImage(160, 90, QImage.Format.Format_RGB888))
    view.show_marks(((0.5, 0.0), (0.5, 1.0)), [(0.25, 0.5)])
    view.grab()
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(100, 200))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(100, 20))  # off it
    QTest.mouseClick(view, Qt.MouseButton.RightButton, pos=QPoint(100, 200))
    assert clicks == [(0.25, (200 - 87.5) / 225)]
    assert view.to_widget((0.25, 0.5)) == QPointF(100, 200)
