"""The window: cameras, the video, moving through it."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import av
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from app import main_window as mw
from app import output_list, session
from app.lines import parse_time, scale_time, to_line_scale
from app.main_window import start_analyzer
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
    wait_until(win.isActiveWindow)  # keys reach the shortcuts of the active window
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
    wait_until(win.isActiveWindow)  # keys reach the shortcuts of the active window
    wait_until(showing(win, START + 69 * 33))
    win.number.setFocus()
    QTest.keyClicks(win.number, "15")
    QTest.keyClick(win.number, Qt.Key.Key_Left)
    wait_until(showing(win, START + 68 * 33))
    QTest.keyClick(win.number, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    wait_until(showing(win, START + 58 * 33))
    QTest.keyClick(win.number, Qt.Key.Key_End)
    wait_until(showing(win, START + 69 * 33))
    assert win.number.text() == "15"
    win.step(-5)
    QTest.keyClicks(win.number, "L")  # a number may hold an L: it is typed
    assert win.number.text() == "15L"
    assert not win.live
    QTest.keyClick(win.number, Qt.Key.Key_Backspace)
    assert win.number.text() == "15"


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


def line(number: int, place: int, action: str = "nextLap") -> str:
    """A chronometer's line for frame ``place`` of the recording."""
    moment = scale_time(to_line_scale(START + place * 33, False))
    return f"{number}#{moment}#{action}#"


@pytest.fixture
def files(recording: Path) -> tuple[Path, Path]:
    results, out = recording / "results.txt", recording / "out.txt"
    results.write_text(
        "".join(f"{line(n, p)}\n" for n, p in ((7, 10), (8, 30), (9, 50)))
    )
    session.save(
        {
            **session.DEFAULTS,
            "cameras": [CAMERA],
            "input": "results.txt",
            "output": "out.txt",
        }
    )
    return results, out


def test_input_lines_reach_the_output_and_both_lists_follow_the_video(
    files: tuple[Path, Path], make_window: Callable[[], mw.MainWindow]
) -> None:
    results, out = files
    win = make_window()
    assert out.read_text().splitlines() == results.read_text().splitlines()
    assert win.input_button.text() == "Input: results.txt"
    rows = win.output_view.lines.rows
    assert [(r.number, r.action, r.note) for r in rows] == [
        ("7", "nextLap", ""),
        ("8", "nextLap", ""),
        ("9", "nextLap", ""),
    ]
    assert rows[0].time == line(7, 10).split("#")[1].split(" ")[1]
    wait_until(showing(win, START + 69 * 33))
    assert win.input_view.lines.near == 2
    win.step(-40)  # frame 29: the second line is nearest
    assert win.output_view.lines.near == 1
    assert win.input_view.lines.near == 1
    with results.open("a") as f:
        f.write(line(10, 60) + "\n")
    win.poll()
    assert [r.number for r in win.output_view.lines.rows] == ["7", "8", "9", "10"]
    assert out.read_text().splitlines()[-1] == line(10, 60)


def test_picking_a_line_moves_the_video_to_its_time(
    files: tuple[Path, Path], make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    win.resize(1200, 800)
    wait_until(showing(win, START + 69 * 33))
    view = win.input_view
    QTest.mouseClick(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=view.visualRect(view.lines.index(1, 0)).center(),
    )
    wait_until(showing(win, START + 30 * 33))
    assert not win.live
    assert view.chosen() == 1


def test_a_changed_input_line_waits_for_copy_to_output(
    files: tuple[Path, Path], make_window: Callable[[], mw.MainWindow]
) -> None:
    results, out = files
    win = make_window()
    win.copy_input()
    assert (
        win.statusBar().currentMessage() == "Choose a changed line of the input first"
    )
    changed = line(8, 31)
    results.write_text("".join(f"{t}\n" for t in (line(7, 10), changed, line(9, 50))))
    win.poll()
    assert out.read_text().splitlines()[1] == line(8, 30)
    row = win.input_view.lines.rows[1]
    assert row.warn
    assert row.note == f"changed; taken as {line(8, 30)}"
    win.input_view.selectRow(0)
    win.copy_input()
    assert win.statusBar().currentMessage() == "That line is as it was taken"
    win.input_view.selectRow(1)
    win.copy_input()
    assert out.read_text().splitlines()[1] == changed
    assert not win.input_view.lines.rows[1].warn
    assert win.input_view.chosen() == 1
    assert journal(out)[-1]["op"] == "copy"


def test_a_copy_the_disk_refuses_is_said(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, _ = files
    win = make_window()
    results.write_text(
        "".join(f"{t}\n" for t in (line(7, 11), line(8, 30), line(9, 50)))
    )
    win.poll()
    win.input_view.selectRow(0)

    def full(path: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(output_list, "_write_in_one_step", full)
    win.copy_input()
    assert "cannot be written: disk full" in win.statusBar().currentMessage()


def test_files_that_cannot_be_followed_are_said(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, out = files
    win = make_window()
    out.write_text("edited by hand\n")
    win.poll()
    assert "changed outside PhotoFinish" in win.statusBar().currentMessage()
    assert out.read_text().splitlines() == results.read_text().splitlines()
    with results.open("a") as f:
        f.write(line(10, 60) + "\n")

    def full(path: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(output_list, "_write_in_one_step", full)
    win.poll()
    assert "cannot be followed: disk full" in win.statusBar().currentMessage()


def test_the_input_is_chosen_and_never_the_output(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, out = files
    win = make_window()
    for answer in ("", str(out)):
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *args, a=answer: (a, "")
        )
        win.choose_input()
        assert session.load()["input"] == "results.txt"
    assert win.statusBar().currentMessage() == "The input cannot be the output file"
    other = results.with_name("other.txt")
    other.write_text(line(20, 5) + "\n")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(other), ""))
    win.choose_input()
    assert session.load()["input"] == str(other)
    assert [r.number for r in win.input_view.lines.rows] == ["20"]


def answer(monkeypatch: pytest.MonkeyPatch, text: str, ok: bool = True) -> None:
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kw: (text, ok))


def test_the_four_corrections_and_nothing_else(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US4's independent test: a time from a frame, a number, one added, one removed."""
    results, out = files
    written = results.read_bytes()
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.output_view.selectRow(1)  # 8, taken at frame 30
    win.step(-36)  # frame 33
    win.time_from_frame()
    assert out.read_text().splitlines()[1] == line(8, 33)
    assert win.output_view.chosen() == 1
    win.output_view.selectRow(0)
    answer(monkeypatch, "17")
    win.change_number()
    assert out.read_text().splitlines()[0] == line(17, 10)
    win.number.setText("21")
    win.add_crossing()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    win.output_view.selectRow(3)  # 9, frame 50
    win.remove_line()
    assert win.output_view.chosen() is None
    assert out.read_text().splitlines() == [line(17, 10), line(8, 33), line(21, 33)]
    entries = journal(out)[3:]  # after the three lines taken
    assert [e["op"] for e in entries] == ["time", "number", "add", "remove"]
    assert entries[0]["before"] == line(8, 30)
    assert entries[0]["camera"] == "cam1"
    assert results.read_bytes() == written
    win.poll()  # the input does not bring the removed line back
    assert len(out.read_text().splitlines()) == 3


def test_a_typed_time_must_be_a_time(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, out = files
    win = make_window()
    win.output_view.selectRow(2)
    answer(monkeypatch, "11:35:29")
    win.type_time()
    assert "is not a time like" in win.statusBar().currentMessage()
    answer(monkeypatch, "", ok=False)
    win.type_time()
    typed = line(9, 50).split("#")[1][:-3] + "999"
    answer(monkeypatch, f" {typed} ")
    win.type_time()
    assert out.read_text().splitlines()[2] == f"9#{typed}#nextLap#"
    assert journal(out)[-1]["method"] == "typed"


def test_corrections_need_a_line_a_frame_a_number_and_a_disk(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, out = files
    win = make_window()
    before = out.read_text()
    for correct in (
        win.time_from_frame,
        win.type_time,
        win.change_number,
        win.remove_line,
    ):
        correct()
        assert win.statusBar().currentMessage() == "Choose a line of the output first"
    win.output_view.selectRow(0)
    answer(monkeypatch, " # ")
    win.change_number()
    assert win.statusBar().currentMessage() == "A crossing needs a number"
    answer(monkeypatch, "18", ok=False)
    win.change_number()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No
    )
    win.remove_line()

    def full(path: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(output_list, "_write_in_one_step", full)
    answer(monkeypatch, "18")
    win.change_number()
    assert "cannot be written: disk full" in win.statusBar().currentMessage()
    assert out.read_text() == before
    win.camera_list.setCurrentRow(-1)
    win.output_view.selectRow(0)
    win.time_from_frame()
    assert win.statusBar().currentMessage() == "There is no frame to take the time from"


BAR = 1_761_716_129_455  # at 60 fps, the bar crosses the centre between frames 2 and 3


@pytest.fixture
def bar(base: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The test camera's bar at 60 fps, 1280 wide, and an output to time on."""
    camera = {**CAMERA, "settings": {"fps": 60, "scene": "bar"}}
    session.save({**session.DEFAULTS, "cameras": [camera], "output": "out.txt"})
    writer = SegmentWriter(base / "video" / "cam1", fps=60)
    for k in range(6):
        ms = BAR + round(k * 1000 / 60)
        writer.write(render(ms, 1280, 720, "bar"), ms)
    writer.close()
    beating(base)
    return base / "out.txt"


def edge(place: int) -> tuple[float, float]:
    """Where the bar's leading edge is on frame ``place``, as the camera drew it."""
    ms = BAR + round(place * 1000 / 60)
    return (ms * 1280 // 1000 % 1280 / 1280, 0.5)


def test_the_caliper_reads_the_bar_crossing_within_a_millisecond(
    bar: Path, make_window: Callable[[], mw.MainWindow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """US5's independent test and SC-004: the bar crosses at .500 of each second."""
    win = make_window()
    wait_until(lambda: win.place == 5)
    offered: list[str] = []

    def accept(*args: Any, text: str = "", **kw: Any) -> tuple[str, bool]:
        offered.append(text)
        return text, True

    monkeypatch.setattr(QInputDialog, "getText", accept)
    win.number.setText("15")
    win.step(-3)  # frame 2: the edge before the centre line
    win.picture_clicked(edge(2))
    assert "other side of the line" in win.statusBar().currentMessage()
    assert win.view.marks == [edge(2)]
    win.step(1)
    assert win.view.marks == []
    win.picture_clicked(edge(3))
    true = to_line_scale(BAR - 455 + 500, False)
    (time_text,) = offered
    read = parse_time(time_text)
    assert read is not None
    assert abs(read - true) <= 1
    assert bar.read_text() == f"15#{time_text}#nextLap#\n"
    entry = journal(bar)[-1]
    assert entry["method"] == "interpolated"
    assert entry["frames"][0][2] == BAR + round(2 * 1000 / 60)
    assert entry["frames"][1][2] == BAR + round(3 * 1000 / 60)
    assert 0 < entry["fraction"] < 1
    assert win.number.text() == ""
    assert win.output_view.lines.rows[0].note == "between two frames"


def test_the_caliper_does_not_extrapolate_and_needs_somewhere_to_put_the_time(
    bar: Path, make_window: Callable[[], mw.MainWindow], monkeypatch: pytest.MonkeyPatch
) -> None:
    win = make_window()
    wait_until(lambda: win.place == 5)
    win.picture_clicked(edge(5))
    win.step(-1)
    win.picture_clicked(edge(4))
    assert "does not extrapolate" in win.statusBar().currentMessage()
    win.step(-2)
    win.picture_clicked(edge(2))  # with frame 4's point: the line lies between
    assert "type a number" in win.statusBar().currentMessage()
    win.number.setText("16")
    answer(monkeypatch, "", ok=False)
    win.picture_clicked(edge(2))
    assert win.caliper == []
    assert bar.read_text() == ""


def test_an_adjusted_caliper_time_is_typed_and_sets_the_chosen_line(
    bar: Path, make_window: Callable[[], mw.MainWindow], monkeypatch: pytest.MonkeyPatch
) -> None:
    win = make_window()
    wait_until(lambda: win.place == 5)
    win.number.setText("15")
    win.add_crossing()
    win.output_view.selectRow(0)
    win.step(-3)
    win.picture_clicked(edge(2))
    win.step(1)
    answer(monkeypatch, "11:35")
    win.picture_clicked(edge(3))
    assert "is not a time like" in win.statusBar().currentMessage()
    win.picture_clicked(edge(3))
    win.step(-1)
    answer(monkeypatch, "20389 11:35:29.500")
    win.picture_clicked(edge(2))
    assert bar.read_text() == "15#20389 11:35:29.500#nextLap#\n"
    assert journal(bar)[-1]["method"] == "typed"
    assert journal(bar)[-1]["frames"] is not None


def test_the_finish_line_is_drawn_with_two_clicks(
    bar: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    wait_until(lambda: win.place == 5)
    win.draw_finish_line()
    win.picture_clicked((0.4, 0.1))
    assert win.view.marks == [(0.4, 0.1)]
    win.picture_clicked((0.6, 0.9))
    assert session.load()["cameras"][0]["finish_line"] == [[0.4, 0.1], [0.6, 0.9]]
    assert win.view.line == ((0.4, 0.1), (0.6, 0.9))
    assert win.statusBar().currentMessage() == "The finish line is drawn"
    assert win.drawing is None


def test_a_finish_line_needs_a_camera(win: mw.MainWindow) -> None:
    win.draw_finish_line()
    assert win.statusBar().currentMessage() == "Add a camera first"
    win.picture_clicked((0.5, 0.5))
    assert win.caliper == []
    win._show_marks()
    assert win.view.line is None


def test_a_moment_picked_between_two_frames_is_a_hand_time(
    bar: Path, make_window: Callable[[], mw.MainWindow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """US5's second scenario: the timeline zoomed until a frame interval is wide."""
    win = make_window()
    win.resize(1200, 700)
    wait_until(lambda: win.place == 5)
    third = BAR + round(2 * 1000 / 60)
    win.timeline.zoom(0.0001, win.timeline.x_at(third))
    x = round(win.timeline.x_at(third + 8))
    QTest.mouseClick(win.timeline, Qt.MouseButton.LeftButton, pos=QPoint(x, 20))
    assert "type a number" in win.statusBar().currentMessage()
    win.number.setText("15")
    accepted: list[str] = []

    def accept(*args: Any, text: str = "", **kw: Any) -> tuple[str, bool]:
        accepted.append(text)
        return text, True

    monkeypatch.setattr(QInputDialog, "getText", accept)
    QTest.mouseClick(win.timeline, Qt.MouseButton.LeftButton, pos=QPoint(x, 20))
    picked = win.timeline.ms_at(x)
    assert accepted == [scale_time(to_line_scale(picked, False))]
    assert bar.read_text() == f"15#{accepted[0]}#nextLap#\n"
    entry = journal(bar)[-1]
    assert entry["method"] == "hand"
    assert [f[2] for f in entry["frames"]] == [third, BAR + round(3 * 1000 / 60)]
    assert win.output_view.lines.rows[0].note == "picked by hand"
    exact = BAR + round(3 * 1000 / 60)
    win.number.setText("16")
    win.pick_between(exact)  # on a frame: between it and the one before
    assert [f[2] for f in journal(bar)[-1]["frames"]] == [third, exact]


FLASH = 1_761_716_130_000  # the test camera flashes for 100 ms every 5 s
SKEW = 1234  # the second camera's clock runs this much ahead


def bright(view: Any) -> bool:
    """The picture is the flash: white in the middle."""
    image = view.image.convertToFormat(QImage.Format.Format_RGB888)
    return QImage.pixelColor(image, image.width() // 2, image.height() // 2).red() > 200


@pytest.fixture
def two(base: Path) -> None:
    """Side at 30 fps and Front at 25 fps, its clock ahead: both film one flash."""
    cameras = [
        {"id": "cam1", "name": "Side", "connection": "test", "settings": {"fps": 30}},
        {"id": "cam2", "name": "Front", "connection": "test", "settings": {"fps": 25}},
    ]
    session.save({**session.DEFAULTS, "cameras": cameras, "output": "out.txt"})
    for camera_id, step, skew in (("cam1", 33, 0), ("cam2", 40, SKEW)):
        writer = SegmentWriter(base / "video" / camera_id, fps=1000 / step)
        for k in range(26):
            true = FLASH - 500 + k * step
            writer.write(render(true, 640, 360, "flash"), true + skew)
        writer.close()
        beating(base, camera_id)


def test_two_cameras_show_one_moment_once_aligned_on_a_flash(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    """US6's independent test: the flash shows on both within one frame interval."""
    win = make_window()
    side, front = win.cameras["cam1"], win.cameras["cam2"]
    wait_until(lambda: side.shown == 25 and front.shown is not None)
    win.seek_ms(FLASH + 28)  # Side's flash frame: its frames are at -5 and +28
    wait_until(lambda: bright(side.view))
    assert not bright(front.view)  # not aligned yet: its flash is 1234 ms later
    win.mark_event()
    assert "now show it on the other cameras" in win.statusBar().currentMessage()
    win.picture_clicked((0.5, 0.5), "cam2")  # choosing Front by its picture
    assert win.current == "cam2"
    win.seek_ms(FLASH + SKEW + 20)  # Front's flash frame, on its own clock
    wait_until(lambda: bright(front.view))
    win.mark_event()
    offset = session.load()["cameras"][1]["offset_ms"]
    assert offset == FLASH + 28 - (FLASH + 20 + SKEW)  # -SKEW within a frame
    said = win.statusBar().currentMessage()
    assert said == f"Front is aligned on the event: {offset:+d} ms"
    win.camera_list.setCurrentRow(0)
    win.step(-3)
    wait_until(lambda: not bright(side.view) and not bright(front.view))
    win.seek_ms(FLASH + 28)
    wait_until(lambda: bright(side.view) and bright(front.view))
    assert front.shown is not None
    assert abs(front.index.frame(front.shown).ms + offset - (FLASH + 28)) < 40


def test_a_crossing_timed_on_the_second_camera_names_it(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    win = make_window()
    wait_until(lambda: win.place is not None)
    win.mark_event()  # marking again on the same camera moves the event
    win.mark_event()
    win.camera_list.setCurrentRow(1)
    assert win.cameras["cam2"].view.chosen
    assert not win.cameras["cam1"].view.chosen
    win.number.setText("15")
    win.add_crossing()
    assert journal(base / "out.txt")[-1]["camera"] == "cam2"


def test_an_event_needs_a_frame(win: mw.MainWindow) -> None:
    win.mark_event()
    assert win.statusBar().currentMessage() == "Show the event on a camera first"


def test_a_cameras_own_file_is_shown_beside_the_live_ones_once_aligned(
    base: Path, make_window: Callable[[], mw.MainWindow], spawned: list[str]
) -> None:
    """US8's fourth scenario: a recording from a camera's card, after the race."""
    card = base / "DCIM0001.mkv"
    with av.open(str(card), "w") as container:
        container.metadata["creation_time"] = "2020-01-01T00:00:00Z"
        stream = container.add_stream("mpeg4", rate=25)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
        for k in range(26):
            picture = render(FLASH - 500 + k * 40, 640, 360, "flash")
            frame = av.VideoFrame.from_ndarray(picture)
            frame.pts = k
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    written = card.read_bytes()
    cameras = [
        {"id": "cam1", "name": "Side", "connection": "test", "settings": {"fps": 30}},
        {
            "id": "cam2",
            "name": "Card",
            "connection": "file",
            "settings": {"path": "DCIM0001.mkv"},
            "record": False,
        },
    ]
    session.save({**session.DEFAULTS, "cameras": cameras})
    writer = SegmentWriter(base / "video" / "cam1", fps=30)
    for k in range(26):
        true = FLASH - 500 + k * 33
        writer.write(render(true, 640, 360, "flash"), true)
    writer.close()
    beating(base, "cam1")
    win = make_window()
    side, own = win.cameras["cam1"], win.cameras["cam2"]
    assert spawned == []  # the file is not recorded
    assert own.item.text() == "Card: not recording"
    wait_until(lambda: side.shown is not None)
    win.seek_ms(FLASH + 28)
    wait_until(lambda: bright(side.view))
    win.mark_event()
    win.camera_list.setCurrentRow(1)
    created = 1_577_836_800_000  # its creation time: frames start there
    win.seek_ms(created + 520)  # its flash frame: k = 13
    wait_until(lambda: bright(own.view))
    win.mark_event()
    win.camera_list.setCurrentRow(0)
    win.seek_ms(FLASH - 400)
    wait_until(lambda: not bright(side.view) and not bright(own.view))
    win.seek_ms(FLASH + 28)
    wait_until(lambda: bright(side.view) and bright(own.view))
    assert card.read_bytes() == written


AHEAD = 2500  # the chronometer's clock runs this much ahead of the video's


def test_the_video_is_aligned_with_the_timing_source_on_one_passing(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    """US7's independent test: one input line and its frame align the rest."""
    results, out = recording / "results.txt", recording / "out.txt"
    passings = [(7, 10), (8, 30), (9, 50)]
    results.write_text(
        "".join(
            f"{n}#{scale_time(to_line_scale(START + p * 33 + AHEAD, False))}#nextLap#\n"
            for n, p in passings
        )
    )
    session.save(
        {
            **session.DEFAULTS,
            "cameras": [CAMERA],
            "input": "results.txt",
            "output": "out.txt",
        }
    )
    win = make_window()
    win.align_source()
    assert (
        win.statusBar().currentMessage() == "Choose the input line of the passing first"
    )
    win.input_view.selectRow(0)
    win.seek_line(win.input_view.lines.rows[0].ms or 0)
    wait_until(showing(win, START + 69 * 33))  # 2.5 s off: the newest frame is nearest
    win.seek_ms(START + 10 * 33)  # the referee finds the passing by eye
    win.align_source()
    assert session.load()["source_offset_ms"] == AHEAD
    assert win.source_label.text() == f"source {AHEAD:+d} ms"
    win.seek_line(
        win.input_view.lines.rows[2].ms or 0
    )  # the third line opens on its rider
    wait_until(showing(win, START + 50 * 33))
    win.number.setText("21")
    win.add_crossing()
    added = out.read_text().splitlines()[-1]
    assert (
        added
        == f"21#{scale_time(to_line_scale(START + 50 * 33 + AHEAD, False))}#nextLap#"
    )
    assert journal(out)[-1]["offsets"] == {"camera_ms": 0, "source_ms": AHEAD}


def test_aligning_needs_a_frame_and_a_line_with_a_time(
    files: tuple[Path, Path], make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    results, _ = files
    win = make_window()
    win.camera_list.setCurrentRow(-1)
    win.align_source()
    assert win.statusBar().currentMessage() == "Show the frame of the passing first"
    win.camera_list.setCurrentRow(0)
    with results.open("a") as f:
        f.write("11##\n")
    win.poll()
    win.input_view.selectRow(3)
    win.align_source()
    assert win.statusBar().currentMessage() == "That line has no time to align on"


def test_finding_riders_is_set_up_beside_the_video(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """002's settings: off by default, a model or motion only, a zone drawn."""
    win = make_window()
    view = win.cameras["cam1"].view
    wait_until(lambda: win.place is not None)
    assert not win.analysis_box.isChecked()
    assert view.zone is None
    win.analysis_box.setChecked(True)
    assert session.load()["analysis"] == {"on": True, "model": ""}
    assert view.zone == ((0.35, 0.0), (0.65, 1.0))
    model = recording / "yolox_s.onnx"
    for chosen in ("", str(model)):
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, c=chosen: (c, "")
        )
        win.choose_model()
    assert session.load()["analysis"]["model"] == str(model)
    assert win.model_button.text() == "Model: yolox_s.onnx"
    win._set_model("")
    assert win.model_button.text() == "Model..."
    win.draw_zone()
    assert "corner of the zone" in win.statusBar().currentMessage()
    win.picture_clicked((0.6, 0.9))
    win.picture_clicked((0.4, 0.1))
    assert session.load()["cameras"][0]["zone"] == [[0.6, 0.9], [0.4, 0.1]]
    assert view.zone == ((0.4, 0.1), (0.6, 0.9))
    assert win.statusBar().currentMessage() == "The zone is drawn"
    view.grab()


def stretch_files(base: Path, stretches: list[list[int]]) -> None:
    folder = base / "video" / "cam1"
    (folder / "x.activity.json").write_text(json.dumps({"stretches": stretches}))
    done = {"done_ms": START + 2277, "state": "waiting"}
    (folder / "analyzer.json").write_text(json.dumps(done))


def test_the_analysis_marks_riders_and_the_keys_jump_between_them(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
) -> None:
    """002 US1: stretches on the timeline, Next and Previous rider, progress."""
    first, second = (START + 600, START + 800), (START + 1900, START + 2100)
    stretch_files(recording, [list(first), list(second)])
    win = make_window()
    win.show()
    win.activateWindow()
    wait_until(win.isActiveWindow)
    wait_until(showing(win, START + 69 * 33))
    win.next_rider()
    assert win.statusBar().currentMessage() == "Turn on finding riders first"
    assert analyzers == []
    win.analysis_box.setChecked(True)
    assert [a.camera_id for a in analyzers] == ["cam1"]
    assert win.timeline.stretches == [first, second]
    assert win.camera_list.item(0).text().endswith("; riders up to date")
    win.seek_ms(START)
    win.next_rider()
    wait_until(showing(win, START + 18 * 33))  # the frame nearest the first start
    QTest.keyClick(win, Qt.Key.Key_PageDown)
    wait_until(showing(win, START + 58 * 33))  # nearest the second
    win.next_rider()
    assert win.statusBar().currentMessage() == "No rider after this moment"
    QTest.keyClick(win, Qt.Key.Key_PageUp)
    wait_until(showing(win, START + 18 * 33))
    win.previous_rider()
    assert win.statusBar().currentMessage() == "No rider before this"
    win.analysis_box.setChecked(False)
    assert not analyzers[0].running
    assert win.timeline.stretches == []


def test_an_analyser_that_dies_is_started_again_and_a_new_zone_restarts_it(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
) -> None:
    session.save({**session.load(), "analysis": {"on": True, "model": ""}})
    win = make_window()
    camera = win.cameras["cam1"]
    assert len(analyzers) == 1
    assert win.camera_list.item(0).text().endswith("; riders not found yet")
    analyzers[0].running = False  # it died
    win.poll()
    assert len(analyzers) == 1  # not again within 30 s
    camera.analyzer_started -= 31
    win.poll()
    assert len(analyzers) == 2
    wait_until(lambda: win.place is not None)
    win.draw_zone()
    win.picture_clicked((0.3, 0.2))
    win.picture_clicked((0.7, 0.9))
    assert not analyzers[1].running
    assert len(analyzers) == 3
    stretch_files(recording, [])
    (recording / "video" / "cam1" / "analyzer.json").write_text(
        json.dumps({"done_ms": START - 10_000})
    )
    win.poll()
    assert win.camera_list.item(0).text().endswith("; riders 12 s behind")


def test_the_real_analyser_finds_three_passes_from_the_window(
    base: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """002 SC-002 in small: the analyser runs beside the window and the recording."""
    monkeypatch.setattr(mw, "start_analyzer", start_analyzer)
    passes = 1_761_716_120_000
    zone = [[0.35, 0.25], [0.65, 0.9]]
    camera = {**CAMERA, "settings": {"fps": 10, "scene": "passes"}, "zone": zone}
    session.save(
        {**session.DEFAULTS, "cameras": [camera], "analysis": {"on": True, "model": ""}}
    )
    writer = SegmentWriter(base / "video" / "cam1", fps=10)
    for k in range(300):
        writer.write(render(passes + k * 100, 640, 360, "passes"), passes + k * 100)
    writer.close()
    beating(base)
    win = make_window()
    activity = win.cameras["cam1"].activity
    wait_until(lambda: len(activity.stretches) == 3, seconds=60)
    win.seek_ms(passes)
    win.next_rider()
    assert win.place is not None
    shown = win.cameras["cam1"].index.frame(win.place).ms
    assert passes + 2_000 <= shown <= passes + 3_500


def test_a_model_that_failed_is_said_and_left_until_another_is_chosen(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
) -> None:
    session.save({**session.load(), "analysis": {"on": True, "model": "x.onnx"}})
    win = make_window()
    failed = {"state": "failed", "detail": "the model cannot be loaded: bad file"}
    (recording / "video" / "cam1" / "analyzer.json").write_text(json.dumps(failed))
    analyzers[0].running = False
    win.cameras["cam1"].analyzer_started -= 31
    win.poll()
    assert len(analyzers) == 1  # failed: not started again by itself
    assert (
        win.camera_list.item(0)
        .text()
        .endswith("; riders the model cannot be loaded: bad file")
    )
    win._set_model("")  # motion only: started again at once
    assert len(analyzers) == 2


def suggest(base: Path, *moments: int) -> None:
    folder = base / "video" / "cam1"
    lines = "".join(
        json.dumps(
            {
                "id": f"cam1-{ms}",
                "camera": "cam1",
                "ms": ms,
                "frames": [["a.mkv", 1, ms - 20], ["a.mkv", 2, ms + 13]],
                "fraction": 0.6,
                "model": "yolox_s.onnx",
            }
        )
        + "\n"
        for ms in moments
    )
    (folder / "suggestions.jsonl").write_text(lines)


def test_suggested_crossings_are_accepted_with_a_number_or_dismissed(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    """002 US2: a list apart from the output, accepted through its usual path."""
    out = recording / "out.txt"
    analysis = {"on": True, "model": "yolox_s.onnx"}
    session.save({**session.load(), "output": "out.txt", "analysis": analysis})
    suggest(recording, START + 1000, START + 2000)
    win = make_window()
    rows = [
        win.suggestion_list.item(i).text() for i in range(win.suggestion_list.count())
    ]
    clock = scale_time(to_line_scale(START + 1000, False)).split(" ")[1]
    assert rows[0] == f"{clock}  Side"
    win.accept_suggestion()
    assert win.statusBar().currentMessage() == "Choose a suggested crossing first"
    first = win.suggestion_list.item(0)
    win.suggestion_list.setCurrentItem(first)
    win._suggestion_picked(first)
    wait_until(showing(win, START + 30 * 33))  # the frame nearest it
    win.accept_suggestion()
    assert "number first" in win.statusBar().currentMessage()
    win.number.setText("15")
    win.accept_suggestion()
    assert (
        out.read_text()
        == f"15#{scale_time(to_line_scale(START + 1000, False))}#nextLap#\n"
    )
    entry = journal(out)[-1]
    assert (entry["method"], entry["model"], entry["fraction"]) == (
        "interpolated",
        "yolox_s.onnx",
        0.6,
    )
    assert entry["frames"] == [["a.mkv", 1, START + 980], ["a.mkv", 2, START + 1013]]
    assert win.suggestion_list.count() == 1
    win.suggestion_list.setCurrentRow(0)
    win.dismiss_suggestion()
    assert win.suggestion_list.count() == 0
    assert len(out.read_text().splitlines()) == 1
    again = make_window()
    assert again.suggestion_list.count() == 0  # decided: not offered again


def test_suggestions_need_a_model(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    session.save({**session.load(), "analysis": {"on": True, "model": ""}})
    suggest(recording, START + 1000)
    win = make_window()
    assert (
        win.suggestion_list.item(0)
        .text()
        .startswith("Suggestions need a detection model")
    )
    win.suggestion_list.setCurrentRow(0)
    win.dismiss_suggestion()
    win._suggestion_picked(win.suggestion_list.item(0))
    win.analysis_box.setChecked(False)
    assert win.suggestion_list.count() == 0


def arriving(results: Path, win: mw.MainWindow, answer: Any) -> Callable[..., Any]:
    """A dialog during which the chronometer writes an earlier crossing and the
    window's poll takes it in, as the timer does under a modal dialog."""

    def dialog(*args: Any, **kwargs: Any) -> Any:
        with results.open("a") as f:
            f.write(line(5, 1) + "\n")
        win.poll()
        return answer

    return dialog


def test_a_correction_hits_the_line_chosen_though_lines_moved_meanwhile(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, out = files
    win = make_window()
    win.output_view.selectRow(1)  # 8
    monkeypatch.setattr(
        QMessageBox,
        "question",
        arriving(results, win, QMessageBox.StandardButton.Yes),
    )
    win.remove_line()
    assert [t.split("#")[0] for t in out.read_text().splitlines()] == ["5", "7", "9"]
    win.output_view.selectRow(2)  # 9
    monkeypatch.setattr(QInputDialog, "getText", arriving(results, win, ("21", True)))
    win.change_number()
    assert [t.split("#")[0] for t in out.read_text().splitlines()] == [
        "5",
        "5",
        "7",
        "21",
    ]
    win.output_view.selectRow(0)
    typed = line(5, 1).split("#")[1]

    def gone(*args: Any, **kwargs: Any) -> tuple[str, bool]:
        assert win.output is not None
        win.output.remove(0)  # removed meanwhile
        return typed, True

    monkeypatch.setattr(QInputDialog, "getText", gone)
    win.type_time()
    assert (
        win.statusBar().currentMessage() == "That crossing is no longer in the output"
    )


def test_a_suggestion_that_could_not_be_written_stays_offered(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.save(
        {
            **session.load(),
            "output": "out.txt",
            "analysis": {"on": True, "model": "m.onnx"},
        }
    )
    suggest(recording, START + 1000)
    win = make_window()
    win.suggestion_list.setCurrentRow(0)
    win.number.setText("15")

    def locked(path: Path, data: bytes) -> None:
        raise PermissionError("held by the protocol generator")

    monkeypatch.setattr(output_list, "_write_in_one_step", locked)
    win.accept_suggestion()
    assert "cannot be written" in win.statusBar().currentMessage()
    assert win.suggestion_list.count() == 1
    assert win.number.text() == "15"
    assert not (recording / "video" / "cam1" / "suggestions.done.jsonl").exists()


def test_a_session_the_disk_refuses_is_said(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(session: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(mw.session, "save", full)
    win.finish.setChecked(True)
    assert win.statusBar().currentMessage() == "The session cannot be saved: disk full"


def test_a_removed_camera_s_analyser_stops_too(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.save({**session.load(), "analysis": {"on": True, "model": ""}})
    win = make_window()
    assert analyzers[0].running
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes
    )
    win.remove_camera()
    assert not analyzers[0].running
