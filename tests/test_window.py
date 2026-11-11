"""The window: cameras, the video, moving through it."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import av
import numpy as np
import pytest
import shiboken6
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QPushButton,
)

from app import analysis, output_list, phone_status, session
from app import main_window as mw
from app.analysis import models
from app.lines import parse_time, scale_time, to_line_scale
from app.main_window import start_analyzer
from app.recorder import launcher
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import read_time, render
from app.widgets.camera_dialog import CameraDialog
from tests.conftest import Zone, settled, wait_until


def downloading(win: mw.MainWindow) -> models.Model | None:
    """The model the window is downloading, if one."""
    return None if win._job is None else win._job.model


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
    assert win.recording_banner.isHidden()  # no camera records: nothing to say


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


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The window's clock, moved by hand: playing shows the frame due by it."""
    now = [1000.0]
    monkeypatch.setattr(mw, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_play_runs_the_video_at_its_own_speed_and_pause_holds_it(
    recording: Path, make_window: Callable[[], mw.MainWindow], clock: list[float]
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    assert win.play_button.text() == "Pause"  # live, the video plays on
    win.step(-60)
    assert win.play_button.text() == "Play"
    win.play()
    assert win.play_timer.isActive()
    assert win.play_button.text() == "Pause"
    clock[0] += 0.33  # ten frames on
    win._play_tick()
    wait_until(showing(win, START + 19 * 33))
    assert not win._frame_on_screen()  # no crossing timed on a moving picture
    win.pause()
    assert not win.play_timer.isActive()
    assert win.play_button.text() == "Play"
    clock[0] += 1.0
    win._play_tick()  # a tick already on its way moves nothing
    settled(win)
    assert shown(win) == START + 19 * 33
    assert win._frame_on_screen()


def test_a_file_played_to_its_end_stops_on_its_last_frame(
    recording: Path, make_window: Callable[[], mw.MainWindow], clock: list[float]
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.cameras["cam1"].settings["record"] = False  # a file opened as it is
    win.step(-9)
    win.play()
    clock[0] += 5.0
    win._play_tick()
    assert not win.live
    assert not win.playing
    assert win.play_button.text() == "Play"
    assert not win.time_label.text().endswith("LIVE")
    settled(win)
    assert shown(win) == START + 69 * 33


def test_stop_stops_playing_even_with_no_frame_to_go_back_to(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    clock: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    win.play()
    camera = win.cameras["cam1"]
    monkeypatch.setattr(camera.index, "nearest", lambda *a, **k: None)
    win.stop()
    assert not win.playing
    assert not win.play_timer.isActive()
    assert win.play_button.text() == "Play"


def test_play_starts_from_the_moment_shown_where_the_camera_has_no_frame(
    recording: Path, make_window: Callable[[], mw.MainWindow], clock: list[float]
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    win.place = None  # a camera chosen that did not film this moment
    win.play()
    assert win.playing
    clock[0] += 0.33
    win._play_tick()
    wait_until(showing(win, START + 19 * 33))


def test_stop_goes_back_to_where_play_started_and_playing_on_reaches_live(
    recording: Path, make_window: Callable[[], mw.MainWindow], clock: list[float]
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    win.play()
    clock[0] += 0.33
    win._play_tick()
    wait_until(showing(win, START + 19 * 33))
    win.stop()
    wait_until(showing(win, START + 9 * 33))
    assert not win.playing
    assert win.play_button.text() == "Play"
    win.play()
    clock[0] += 5.0  # past the newest frame
    win._play_tick()
    assert win.live
    assert not win.play_timer.isActive()
    assert win.play_button.text() == "Pause"
    wait_until(showing(win, START + 69 * 33))


def test_stop_after_the_video_was_moved_only_holds_it(
    recording: Path, make_window: Callable[[], mw.MainWindow], clock: list[float]
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    win.play()
    clock[0] += 0.33
    win._play_tick()
    wait_until(showing(win, START + 19 * 33))
    win.pause()
    win.step(-5)
    win.stop()
    settled(win)
    assert shown(win) == START + 14 * 33  # not back at 9, where Play started
    win.play()
    clock[0] += 5.0
    win._play_tick()  # caught up: Live
    wait_until(showing(win, START + 69 * 33))
    win.stop()
    assert not win.live
    settled(win)
    assert shown(win) == START + 69 * 33


def test_playing_asks_for_the_next_frame_once_the_one_on_its_way_is_shown(
    recording: Path, make_window: Callable[[], mw.MainWindow], clock: list[float]
) -> None:
    """On a decoder slower than the camera every frame shown is one asked for:
    the next waits for it, and a late answer never shows on a camera that has
    no frame at the moment."""
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    camera = win.cameras["cam1"]
    red, blue = (QImage(8, 8, QImage.Format.Format_RGB888) for _ in range(2))
    red.fill(Qt.GlobalColor.red)
    blue.fill(Qt.GlobalColor.blue)
    win.play()
    camera.pending = True  # frame 9 still on its way
    asked = camera.wanted
    assert asked is not None
    clock[0] += 0.33
    win._play_tick()
    assert camera.wanted == asked  # frame 19 waits
    win._decoded(asked, red)
    assert win.view.image == red
    win._play_tick()
    wait_until(lambda: win.view.image != red)  # frame 19, asked now
    assert shown(win) == START + 19 * 33
    late = (camera.id, camera.index.frame(0))
    camera.wanted, camera.pending = None, False  # no frame at this moment
    win._decoded(late, blue)
    assert win.view.image != blue


def test_pause_on_a_frame_already_on_screen_asks_for_nothing_again(
    recording: Path, make_window: Callable[[], mw.MainWindow], clock: list[float]
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    win.play()
    clock[0] += 0.33
    win._play_tick()
    wait_until(showing(win, START + 19 * 33))
    camera = win.cameras["cam1"]
    assert not camera.pending
    asked = camera.wanted
    win.pause()
    assert camera.wanted == asked  # not asked again: no seek, no dimming
    assert not win.view.waiting
    assert win._frame_on_screen()


def test_a_move_while_playing_dims_until_the_frame_moved_to_is_on_screen(
    recording: Path, make_window: Callable[[], mw.MainWindow], clock: list[float]
) -> None:
    """A frame asked for while playing is not dimmed. Moved to it -- a crossing
    clicked, a seek -- the window must still wait for it before timing."""
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    win.play()
    clock[0] += 0.33
    win._play_tick()  # frame 19 asked for, not dimmed
    mw.MainWindow.seek_ms(win, START + 19 * 33)  # straight away, before it arrives
    assert not win.playing
    assert win.view.waiting
    assert not win._frame_on_screen()
    settled(win)
    assert shown(win) == START + 19 * 33
    assert win._frame_on_screen()


def test_playing_does_nothing_while_the_frame_asked_is_on_its_way(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    clock: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    moves: list[int] = []
    real = win._go
    monkeypatch.setattr(win, "_go", moves.append)
    win.play()
    camera = win.cameras["cam1"]
    camera.pending = True
    for _ in range(5):
        clock[0] += 0.015
        win._play_tick()
    assert moves == []
    camera.pending = False
    win._play_tick()
    assert moves == [11]
    monkeypatch.setattr(win, "_go", real)


def test_playing_follows_the_lists_a_few_times_a_second_not_at_every_frame(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    clock: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.step(-60)
    followed: list[int] = []
    monkeypatch.setattr(win, "_follow_lists", followed.append)
    win.play()
    for _ in range(5):  # five frames, a sixth of a second
        clock[0] += 0.033
        win._play_tick()
        win.cameras["cam1"].pending = False
    assert followed == []
    clock[0] += 0.1
    win._play_tick()
    assert len(followed) == 1
    win.pause()
    assert len(followed) == 2  # a held frame: at once


def test_pause_holds_the_live_picture_while_recording_goes_on(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.play_or_pause()
    assert not win.live
    assert win.play_button.text() == "Play"
    record(recording, START + 5000, 10)
    win.poll()
    settled(win)
    assert shown(win) == START + 69 * 33
    win.play_or_pause()
    assert win.playing


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


def test_a_phone_sharing_a_port_says_so_in_the_camera_list(
    make_window: Callable[[], mw.MainWindow],
) -> None:
    phone = {"connection": "rtmp", "settings": {"port": 1935, "path": "live/a"}}
    session.save(
        {
            **session.DEFAULTS,
            "cameras": [
                {**phone, "id": "cam1", "name": "Line"},
                {**phone, "id": "cam2", "name": "Side"},
            ],
        }
    )
    win = make_window()
    lines = [win.camera_list.item(i).text() for i in range(2)]
    assert lines[0].startswith("Line: port 1935 is also Side's: each phone needs")
    assert lines[1].startswith("Side: port 1935 is also Line's: each phone needs")


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
        "rtmp",  # a phone's streaming app, the dialog's first choice
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


def test_a_phone_with_several_lenses_adds_a_camera_for_each(
    win: mw.MainWindow, spawned: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def accept(dialog: CameraDialog) -> CameraDialog.DialogCode:
        dialog.lenses["ultrawide"].setChecked(True)
        return CameraDialog.DialogCode.Accepted

    monkeypatch.setattr(CameraDialog, "exec", accept)
    saved_first: list[bool] = []
    real = launcher.spawn

    def spawn(camera_id: str) -> Any:  # a recorder reads its camera from the session
        saved_first.append(camera_id in {c["id"] for c in session.load()["cameras"]})
        return real(camera_id)

    monkeypatch.setattr(launcher, "spawn", spawn)
    win.add_camera()
    added = [(c["id"], c["name"]) for c in session.load()["cameras"]]
    assert added == [("cam1", "Camera 1 main"), ("cam2", "Camera 1 ultra-wide")]
    assert spawned == ["cam1", "cam2"]
    assert saved_first == [True, True]
    assert win.camera_list.currentRow() == 0  # the first of them chosen


def test_one_camera_alone_and_the_keys_that_switch_between_cameras(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    second = {**CAMERA, "id": "cam2", "name": "Wide"}
    session.save({**session.DEFAULTS, "cameras": [CAMERA, second]})
    record(recording, START, 70, "cam2")
    beating(recording, "cam2")
    win = make_window()
    win.show()
    win.activateWindow()
    wait_until(win.isActiveWindow)  # keys reach the shortcuts of the active window
    side, wide = win.cameras["cam1"], win.cameras["cam2"]
    wait_until(showing(win, START + 69 * 33))
    assert side.view.isVisible() and wide.view.isVisible()
    win.one_camera.click()
    assert side.view.isVisible() and not wide.view.isVisible()
    asked = wide.wanted
    win.step(-10)  # the hidden camera follows the moment, but is not decoded
    wait_until(showing(win, START + 59 * 33))
    assert wide.wanted == asked
    win.number.setFocus()
    QTest.keyClick(win.number, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert win.current == "cam2"
    assert wide.view.isVisible() and not side.view.isVisible()
    wait_until(showing(win, START + 59 * 33))  # at the same moment
    QTest.keyClick(win.number, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert win.current == "cam1"
    QTest.keyClick(win, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert (win.current, win.one_camera.isChecked()) == ("cam2", True)
    QTest.keyClick(win, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert not win.one_camera.isChecked()
    assert side.view.isVisible() and wide.view.isVisible()
    QTest.keyClick(win, Qt.Key.Key_9, Qt.KeyboardModifier.ControlModifier)
    assert (win.current, win.one_camera.isChecked()) == ("cam2", False)  # no camera 9


def test_with_no_camera_chosen_up_is_the_last_and_down_the_first(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    three = [{**CAMERA, "id": f"cam{n}", "name": f"C{n}"} for n in (1, 2, 3)]
    session.save({**session.DEFAULTS, "cameras": three})
    win = make_window()
    win.camera_list.setCurrentRow(-1)
    win.next_camera(-1)
    assert win.camera_list.currentRow() == 2
    win.camera_list.setCurrentRow(-1)
    win.next_camera(1)
    assert win.camera_list.currentRow() == 0


def test_choosing_a_camera_lays_the_views_out_again_only_in_one_camera_mode(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    second = {**CAMERA, "id": "cam2", "name": "Wide"}
    session.save({**session.DEFAULTS, "cameras": [CAMERA, second]})
    win = make_window()
    laid: list[int] = []
    real = win._arrange

    def arrange() -> None:
        laid.append(1)
        real()

    win._arrange = arrange  # type: ignore[method-assign]
    win.camera_list.setCurrentRow(1)
    assert laid == []  # side by side: nothing moves
    win.one_camera.setChecked(True)
    win.camera_list.setCurrentRow(0)
    assert len(laid) == 2  # the mode turned on, then the camera chosen


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
    assert win._free_ids(1) == ["cam2"]  # cam1's recording is still on disk


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


def test_the_corner_says_whether_every_camera_records(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    banner = win.recording_banner
    assert not banner.isHidden()
    assert banner.text() == "RECORDING"
    assert mw.GREEN in banner.styleSheet()
    beating(recording, state="reconnecting", detail="the stream ended")
    win.poll()
    last = scale_time(to_line_scale(START + 69 * 33, False)).split(" ")[1]
    assert banner.text().startswith("NOT RECORDING<br>")
    assert f"Side: no video since {last.split('.')[0]}</span>" in banner.text()
    assert mw.RED in banner.styleSheet()
    beating(recording)  # the camera is back
    win.poll()
    assert banner.text() == "RECORDING"
    assert mw.GREEN in banner.styleSheet()


def test_under_the_banner_each_phone_says_what_may_stop_its_stream(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    now = time.time_ns() // 1_000_000
    beating(
        recording,
        phone={"battery": "9", "charging": "0", "wifi": "-61"}
        | {"at_ms": now, "heard_ms": now},
    )
    win = make_window()
    text = win.phones.text()
    assert not win.phones.isHidden()
    assert text.startswith("Side: ")
    assert f"<span style='color: {mw.RED}'>{phone_status.BATTERY} 9%</span>" in text
    assert f"{phone_status.WIFI} -61 dBm" in text  # fine: no colour of its own
    assert "gray" not in text
    old = {"battery": "57", "charging": "1", "at_ms": START, "heard_ms": START}
    beating(recording, phone=old)
    win.poll()  # a status heard long ago: the phone's last word, greyed, with its time
    last = scale_time(to_line_scale(START, False)).split(" ")[1].split(".")[0]
    assert "color: gray" in win.phones.text()
    assert f"at {last}" in win.phones.text()
    beating(recording)  # a camera that is no phone has no line
    win.poll()
    assert win.phones.isHidden()


def test_a_phone_s_line_greys_once_its_recorder_stops_beating(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    frozen = time.time_ns() // 1_000_000 - 8_000  # its last beat, 8 s ago
    beat = {"state": "recording", "frames": 70, "detail": "", "heartbeat_ms": frozen}
    heard = frozen - 500  # just before
    beat["phone"] = {"battery": "57", "at_ms": heard, "heard_ms": heard}
    (recording / "video" / "cam1" / "recorder.json").write_text(json.dumps(beat))
    win.poll()
    assert "color: gray" in win.phones.text()


def test_the_corner_counts_only_cameras_that_record_and_names_them_as_text(
    base: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    card = {"id": "cam9", "name": "Card", "connection": "file", "record": False}
    session.save({**session.DEFAULTS, "cameras": [card]})
    win = make_window()
    assert win.recording_banner.isHidden()  # a file opened as it is records nothing
    session.save({**session.DEFAULTS, "cameras": [card, {**CAMERA, "name": "<i>"}]})
    win = make_window()
    win.poll()  # its recorder only started: nothing recorded yet
    assert not win.recording_banner.isHidden()
    assert win.recording_banner.text().endswith("&lt;i&gt;: no video yet</span>")


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


@pytest.mark.parametrize(
    ("summer", "dst"),
    [(False, False), (False, True), (True, True), (True, False)],
    ids=[
        "option-off-winter",
        "option-off-summer",
        "option-on-summer",
        "option-on-winter",
    ],
)
def test_the_time_shown_is_the_time_a_crossing_at_the_frame_gets(
    base: Path,
    make_window: Callable[[], mw.MainWindow],
    utc5: Zone,
    summer: bool,
    dst: bool,
) -> None:
    """The referee times by the label: a crossing added at the frame shown gets the
    time it shows, the camera's offset and the timing source's in both, and the
    summer hour too while daylight saving is on, and only then: not in a winter race."""
    # Daylight saving on for the race's moments, an hour back too, and not for now.
    utc5["dst"] = (START / 1000 - 7200, START / 1000 + 3600) if dst else None
    # Every time below is written out, not worked out with the window's arithmetic:
    # at UTC+5, an hour later in summer time, on day 20390 of the line scale.
    hour = 11 if summer and dst else 10
    newest = f"{hour}:35:33.690"  # the newest frame, with the first offsets
    moment = f"{hour}:35:30.607"  # frame 60, with the second
    # The timing source's line for the rider at the newest frame, a second before the
    # video's moment for it with the camera's offset: aligning on it gives -1000 ms.
    passing = f"{hour}:35:33.924"
    (base / "results.txt").write_text(f"7#20390 {passing}#nextLap#\n")
    session.save(
        {
            **session.DEFAULTS,
            "cameras": [{**CAMERA, "offset_ms": 40}],
            "input": "results.txt",
            "output": "out.txt",
            "source_offset_ms": -1234,
            "summer_time": summer,
        }
    )
    record(base, START, 70)
    beating(base)
    win = make_window()
    wait_until(showing(win, START + 69 * 33))  # live, on the newest frame
    record(base, START + 5000, 10)  # and frames go on coming in
    win.poll()
    wait_until(showing(win, START + 5000 + 9 * 33))
    assert win.time_label.text() == f"{newest} LIVE"  # the live label moved on too
    win.number.setText("14")
    win.add_crossing()
    win.input_view.selectRow(0)
    win.align_source()  # the referee aligns again, on that rider
    assert win.session["source_offset_ms"] == -1000
    assert win.time_label.text() == f"{passing} LIVE"  # moved with the alignment
    win.step(-19)
    wait_until(showing(win, START + 60 * 33))  # the frame the referee looks at
    assert win.time_label.text() == moment  # and the time read before the click
    win.number.setText("15")
    win.add_crossing()
    added = (base / "out.txt").read_text().splitlines()
    assert added == [  # in time order, the input's line followed into the output too
        f"15#20390 {moment}#nextLap#",
        f"14#20390 {newest}#nextLap#",
        f"7#20390 {passing}#nextLap#",
    ]
    # Each crossing's entry: its line, the frame it was timed on, the offsets then.
    adds = [e for e in journal(base / "out.txt") if e["op"] == "add"]
    first = {"camera_ms": 40, "source_ms": -1234}
    second = {"camera_ms": 40, "source_ms": -1000}
    assert [(e["after"], e["frames"][0][2], e["offsets"]) for e in adds] == [
        (f"14#20390 {newest}#nextLap#", START + 5000 + 9 * 33, first),
        (f"15#20390 {moment}#nextLap#", START + 60 * 33, second),
    ]
    # And from a line back to the video, with the summer hour or without: crossing 15's
    # opens on frame 60, mid-recording, where an hour off either way is another frame.
    win.seek_line(parse_time(f"20390 {moment}") or 0)
    wait_until(showing(win, START + 60 * 33))
    assert win.time_label.text() == moment


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


def test_a_copy_of_the_output_the_disk_refuses_is_said(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    choose(monkeypatch, recording / "out.txt")
    win.choose_output()
    wait_until(lambda: win.place is not None)
    monkeypatch.setattr(output_list, "_copies", lambda: recording / "out.txt")
    win.number.setText("15")
    win.add_crossing()
    assert win.output is not None
    assert win.output.texts()  # written, whatever the copy
    win._follow_files()  # the poll
    assert "its copy in temp/ cannot be written" in win.statusBar().currentMessage()
    assert win.output.copy_refused is None  # said once


def test_a_copy_refused_is_said_though_the_files_cannot_be_followed(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    choose(monkeypatch, recording / "out.txt")
    win.choose_output()
    assert win.output is not None
    win.output.copy_refused = OSError("temp is read-only")

    def held() -> bool:
        raise OSError("output held")

    monkeypatch.setattr(win.output, "check_outside", held)
    win._follow_files()  # the poll
    assert "its copy in temp/ cannot be written" in win.statusBar().currentMessage()


def test_a_copy_refused_never_hides_a_word_said_once(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    choose(monkeypatch, recording / "out.txt")
    win.choose_output()
    assert win.output is not None
    win.output.copy_refused = OSError("temp is read-only")
    win.output.outside_kept = True  # an outside version kept by the same change
    win._follow_files()  # the poll
    assert win.statusBar().currentMessage() == mw.OUTSIDE
    win._follow_files()  # the next one
    assert "its copy in temp/ cannot be written" in win.statusBar().currentMessage()


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


def test_an_output_whose_journal_refuses_is_opened_and_said(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, out = files
    out.write_text(line(5, 5) + "\n")

    def full(path: Path, data: bytes) -> None:
        raise OSError("read only")

    monkeypatch.setattr(output_list, "_append", full)
    said: list[str] = []
    monkeypatch.setattr(mw.MainWindow, "_say", lambda self, text: said.append(text))
    win = make_window()
    assert win.output is not None
    assert win.follow is not None  # the input is followed into it
    assert said[0] == "Opened; the journal cannot take it: read only"


def test_an_output_held_when_the_window_starts_is_opened_at_a_later_poll(
    files: tuple[Path, Path],
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = mw.OutputList
    held = [PermissionError("held by the protocol generator")]

    def opening(path: Path) -> output_list.OutputList:
        if held:
            raise held.pop()
        return real(path)

    monkeypatch.setattr(mw, "OutputList", opening)
    said: list[str] = []
    monkeypatch.setattr(mw.MainWindow, "_say", lambda self, text: said.append(text))
    win = make_window()
    assert "cannot be opened" in said[0]
    win.poll()
    assert win.output is not None
    assert win.follow is not None
    assert len(win.output.texts()) == 3  # the input followed into it


def test_an_outside_change_found_by_a_new_input_line_is_said_too(
    files: tuple[Path, Path], make_window: Callable[[], mw.MainWindow]
) -> None:
    results, out = files
    win = make_window()
    out.write_text("edited by hand\n")
    with results.open("a") as f:
        f.write(line(10, 60) + "\n")  # taken in the same poll, before the check
    win.poll()
    assert "changed outside PhotoFinish" in win.statusBar().currentMessage()
    assert len(list(out.parent.glob("out.txt.outside-*"))) == 1


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
    monkeypatch.undo()
    monkeypatch.setattr(output_list, "_append", full)
    out.write_text("edited again\n")
    win.poll()
    said = win.statusBar().currentMessage()
    assert said == "Written; the journal cannot take it: disk full"
    assert win.output is not None  # written back all the same
    assert out.read_text().splitlines() == win.output.texts()


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
    assert not win.this_camera_only.isEnabled()  # out of the edit mode
    win.edit_line.setChecked(True)
    assert win.edit_line.isChecked() and win.this_camera_only.isEnabled()
    win.picture_clicked((0.4, 0.1))
    assert win.view.marks == [(0.4, 0.1)]
    win.picture_clicked((0.6, 0.9))
    saved = session.load()
    assert saved["finish_line"] == [[0.4, 0.1], [0.6, 0.9]]  # the common line
    assert saved["cameras"][0]["own_line"] is False
    assert win.view.line == ((0.4, 0.1), (0.6, 0.9))
    said = "The finish line is drawn for every camera that follows it"
    assert win.statusBar().currentMessage() == said
    assert win.drawing == []  # the edit mode stays on for the next
    win.edit_line.setChecked(False)
    assert win.drawing is None and not win.this_camera_only.isEnabled()


def test_a_line_or_zone_without_extent_is_not_kept(
    bar: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    wait_until(lambda: win.place == 5)
    win.edit_line.setChecked(True)
    win.picture_clicked((0.4, 0.1))
    win.picture_clicked((0.4, 0.1))  # a double click
    assert "apart from the first" in win.statusBar().currentMessage()
    assert "finish_line" not in session.load()
    win.picture_clicked((0.6, 0.9))
    assert session.load()["finish_line"] == [[0.4, 0.1], [0.6, 0.9]]
    win.draw_zone()
    win.picture_clicked((0.3, 0.2))
    win.picture_clicked((0.3, 0.8))  # no width
    assert "zone" not in session.load()["cameras"][0]
    win.picture_clicked((0.7, 0.8))
    assert session.load()["cameras"][0]["zone"] == [[0.3, 0.2], [0.7, 0.8]]


def test_a_finish_line_needs_a_camera(win: mw.MainWindow) -> None:
    win.edit_line.setChecked(True)
    assert win.statusBar().currentMessage() == "Add a camera first"
    assert not win.edit_line.isChecked()
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
    assert win.shared_event is None  # both aligned: the next mark is a new event
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
    settled(win)
    assert win.cameras["cam2"].view.chosen
    assert not win.cameras["cam1"].view.chosen
    win.number.setText("15")
    win.add_crossing()
    assert journal(base / "out.txt")[-1]["camera"] == "cam2"


def test_an_event_left_unaligned_is_forgotten_after_a_while(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    win = make_window()
    wait_until(lambda: win.place is not None)
    win.mark_event()
    assert win.shared_event is not None
    win.shared_event.since -= mw.shared_event.EVENT_S + 1  # an hour later
    win.camera_list.setCurrentRow(1)
    settled(win)
    win.mark_event()
    assert win.statusBar().currentMessage().startswith("Event marked on")
    assert "offset_ms" not in session.load()["cameras"][1]


def test_nothing_is_aligned_on_a_frame_still_on_its_way(
    files: tuple[Path, Path], make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    win.poll()
    win.input_view.selectRow(0)
    win.view.show_waiting()  # stepped: the picture is the frame before
    win.align_source()
    assert "still on its way" in win.statusBar().currentMessage()
    assert session.load()["source_offset_ms"] == 0  # nothing aligned
    win.mark_event()
    assert win.shared_event is None


def test_a_file_camera_without_its_path_does_not_stop_the_window(
    base: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    camera = {"id": "cam9", "name": "Card", "connection": "file", "record": False}
    session.save({**session.DEFAULTS, "cameras": [camera]})  # edited by hand
    win = make_window()
    assert list(win.cameras) == ["cam9"]


def test_a_recorder_that_cannot_be_started_is_said_in_the_camera_list(
    base: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.recorder import launcher

    def refused(camera_id: str) -> None:
        raise OSError("the program was moved")

    session.save({**session.DEFAULTS, "cameras": [CAMERA]})
    monkeypatch.setattr(launcher, "spawn", refused)
    win = make_window()
    win.poll()  # goes on: the input would still be taken
    text = win.camera_list.item(0).text()
    assert text.endswith("the recorder cannot be started: the program was moved")


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
    assert not win.crossings_box.isEnabled()  # with finding riders only
    win.analysis_box.setChecked(True)
    assert win.crossings_box.isEnabled()
    assert session.load()["analysis"] == {"on": True, "model": "", "crossings": False}
    assert view.zone == ((0.35, 0.0), (0.65, 1.0))
    assert win.model_box.currentText() == "Motion only"
    own_file = win.model_box.findData(mw._OWN_FILE)
    model = recording / "my_yolox.onnx"
    for chosen in ("", str(model)):
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, c=chosen: (c, "")
        )
        win._model_chosen(own_file)
        own_file = win.model_box.findData(mw._OWN_FILE)
    assert session.load()["analysis"]["model"] == str(model)
    assert win.model_box.currentText() == "Model: my_yolox.onnx"
    win._model_chosen(win.model_box.findData(""))
    assert win.model_box.currentText() == "Motion only"
    assert win.model_box.findData(str(model)) == -1  # a file no longer chosen: gone
    win.draw_zone()
    assert "corner of the zone" in win.statusBar().currentMessage()
    win.picture_clicked((0.6, 0.9))
    win.picture_clicked((0.4, 0.1))
    assert session.load()["cameras"][0]["zone"] == [[0.6, 0.9], [0.4, 0.1]]
    assert view.zone == ((0.4, 0.1), (0.6, 0.9))
    assert win.statusBar().currentMessage() == "The zone is drawn"
    view.grab()


def test_a_preset_missing_on_disk_is_downloaded_before_the_analysers_start(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An event folder copied without models/: the preset it uses comes back by
    itself, and the analysers wait for it instead of failing on it."""
    saved = session.load()
    saved["analysis"] = {"on": True, "model": models.MODELS[2].file}
    session.save(saved)
    fetched: list[str] = []
    gate = threading.Event()

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        gate.wait(5)
        fetched.append(model.key)
        return Path(model.file)

    monkeypatch.setattr(mw.models, "NUMBER_MODELS", ())  # the detector alone
    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: model.key in fetched)
    win = make_window()
    win.poll()
    assert downloading(win) is models.MODELS[2]
    assert analyzers == []  # no analyser fails on a model not there yet
    gate.set()
    wait_until(lambda: downloading(win) is None)
    assert fetched == ["yolox_s"]
    assert [a.camera_id for a in analyzers] == ["cam1"]


def gated_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[threading.Event, list[str]]:
    """Downloads that wait for the gate; the detector alone, no number reader."""
    fetched: list[str] = []
    gate = threading.Event()

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        gate.wait(5)
        fetched.append(model.key)
        return Path(model.file)

    monkeypatch.setattr(mw.models, "NUMBER_MODELS", ())
    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: model.key in fetched)
    return gate, fetched


def test_numbers_and_crossings_turned_off_while_the_model_comes_stay_off(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nano = models.MODELS[0]
    saved = session.load()
    saved["analysis"] = {"on": True, "model": nano.file, "crossings": True}
    session.save(saved)
    gate, _ = gated_fetch(monkeypatch)
    win = make_window()
    assert downloading(win) is nano  # the model in use, missing on this disk
    win.crossings_box.setChecked(False)  # then turned off on purpose
    gate.set()
    wait_until(lambda: downloading(win) is None)
    assert not win.crossings_box.isChecked()
    assert analysis.settings(session.load()) == {
        **saved["analysis"],
        "crossings": False,
    }


def test_a_detector_chosen_to_download_turns_numbers_and_crossings_on_at_once(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    nano = models.MODELS[0]
    gate, _ = gated_fetch(monkeypatch)
    win._model_chosen(win.model_box.findData(nano.file))
    assert win.crossings_box.isChecked()  # as one ready does
    win.crossings_box.setChecked(False)  # then turned off on purpose
    gate.set()
    wait_until(lambda: analysis.settings(session.load())["model"] == nano.file)
    assert not win.crossings_box.isChecked()
    assert analysis.settings(session.load())["crossings"] is False


def test_choosing_the_model_in_use_again_restarts_nothing(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nano = models.MODELS[0]
    saved = session.load()
    saved["analysis"] = {"on": True, "model": nano.file}
    session.save(saved)
    monkeypatch.setattr(mw.models, "ready", lambda model: True)
    win = make_window()
    assert [a.camera_id for a in analyzers] == ["cam1"]
    win._model_chosen(win.model_box.findData(nano.file))
    assert len(analyzers) == 1
    assert analyzers[0].running


def test_choosing_another_model_stops_a_download_and_nothing_waits_for_it(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A download trickling in on a venue's mobile link: the referee goes back to
    motion only, and the download stops without a word."""
    stopped = threading.Event()

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        while not cancelled():
            time.sleep(0.01)
        stopped.set()
        raise models.FetchError(f"{model.title}: download stopped")

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: False)
    win._model_chosen(win.model_box.findData(models.MODELS[2].file))
    assert win.model_box.isEnabled()  # another choice stays open
    win._model_chosen(win.model_box.findData(""))
    assert stopped.wait(5)
    QApplication.processEvents()
    assert downloading(win) is None
    assert "stopped" not in win.statusBar().currentMessage()
    assert analysis.settings(session.load())["model"] == ""
    assert win.model_box.currentText() == "Motion only"


def test_a_download_of_another_model_holds_no_analyser_back(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    clock: list[float],
) -> None:
    saved = session.load()
    saved["analysis"] = {"on": True, "model": ""}
    session.save(saved)
    gate = threading.Event()

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        gate.wait(5)
        raise models.FetchError(f"{model.title} cannot be downloaded: offline")

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: False)
    win = make_window()
    assert len(analyzers) == 1
    win._model_chosen(win.model_box.findData(models.MODELS[2].file))
    analyzers[0].running = False  # the analyser of the model in use ends
    clock[0] += 60
    win.poll()
    assert len(analyzers) == 2  # started again: not the model downloading
    gate.set()
    wait_until(lambda: downloading(win) is None)


def test_a_model_chosen_again_is_not_taken_for_the_download_stopped_before(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tiny chosen, stopped, chosen again: the first download, ending late, is not
    taken for the second, and the second's model is the one kept."""
    tiny = models.MODELS[1]
    calls: list[str] = []
    second_started, second_may_end = threading.Event(), threading.Event()

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        calls.append(model.key)
        if len(calls) == 1:
            while not cancelled():
                time.sleep(0.01)
            second_started.wait(5)  # it ends once the same model is asked again
            raise models.FetchError(f"{model.title}: download stopped")
        second_started.set()
        second_may_end.wait(5)
        return Path(model.file)

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: False)
    win._model_chosen(win.model_box.findData(tiny.file))
    win._model_chosen(win.model_box.findData(""))
    win._model_chosen(win.model_box.findData(tiny.file))
    assert second_started.wait(5)
    for _ in range(30):  # the first's "stopped" arrives meanwhile
        QApplication.processEvents()
        time.sleep(0.01)
    assert downloading(win) is tiny
    assert "stopped" not in win.statusBar().currentMessage()
    second_may_end.set()
    wait_until(lambda: analysis.settings(session.load())["model"] == tiny.file)


def test_a_file_dialog_closed_without_a_file_leaves_the_download_going(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yolox_s = models.MODELS[2]
    saved = session.load()
    saved["analysis"] = {"on": True, "model": yolox_s.file}
    session.save(saved)
    may_end = threading.Event()
    stopped: list[bool] = []

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        may_end.wait(5)
        stopped.append(cancelled())
        return Path(model.file)

    monkeypatch.setattr(mw.models, "NUMBER_MODELS", ())  # the detector alone
    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: bool(stopped))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("", ""))
    win = make_window()
    win._model_chosen(win.model_box.findData(mw._OWN_FILE))
    assert downloading(win) is yolox_s
    assert win.model_box.currentText() == yolox_s.label
    may_end.set()
    wait_until(lambda: downloading(win) is None)
    assert stopped == [False]
    assert [a.camera_id for a in analyzers] == ["cam1"]


def test_going_back_to_the_model_in_use_redoes_the_list(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    tiny = models.MODELS[1]

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        progress(5_000_000)
        while not cancelled():
            time.sleep(0.01)
        raise models.FetchError(f"{model.title}: download stopped")

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: False)
    win._model_chosen(win.model_box.findData(tiny.file))
    line = win.model_box.findData(tiny.file)
    wait_until(lambda: win.model_box.itemText(line) == "YOLOX-Tiny: 5 of 21 MB")
    win._model_chosen(win.model_box.findData(models.MODELS[2].file))  # another
    assert win.model_box.itemText(win.model_box.findData(tiny.file)) == tiny.label
    assert win.model_box.currentText() == models.MODELS[2].label  # the one coming
    win._model_chosen(win.model_box.findData(""))
    assert win.model_box.itemText(win.model_box.findData(tiny.file)) == tiny.label
    assert win.model_box.currentText() == "Motion only"


def test_no_analyser_starts_while_the_model_in_use_is_missing(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The start's download of YOLOX-S stopped by choosing YOLOX-Tiny, missing too:
    YOLOX-S stays in use until Tiny is there, and no analyser starts on it."""
    saved = session.load()
    saved["analysis"] = {"on": True, "model": models.MODELS[2].file}
    session.save(saved)
    may_end = threading.Event()

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        while not cancelled() and not may_end.is_set():
            time.sleep(0.01)
        if cancelled():
            raise models.FetchError(f"{model.title}: download stopped")
        raise models.FetchError(f"{model.title} cannot be downloaded: offline")

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: False)
    win = make_window()
    win.poll()
    assert win.camera_list.item(0).text().endswith("; riders: the model is downloading")
    win._model_chosen(win.model_box.findData(models.MODELS[1].file))
    win.poll()
    assert analyzers == []
    assert (
        win.camera_list.item(0)
        .text()
        .endswith(  # Tiny comes, not S in use
            "; riders: the model is not here, choose it to download it"
        )
    )
    may_end.set()
    wait_until(lambda: downloading(win) is None)
    win.poll()
    assert analyzers == []
    assert (
        win.camera_list.item(0)
        .text()
        .endswith("; riders: the model is not here, choose it to download it")
    )


def test_a_missing_model_is_fetched_only_once_finding_riders_is_on(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = session.load()
    saved["analysis"] = {"on": False, "model": models.MODELS[2].file}
    session.save(saved)
    fetched: list[str] = []

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        fetched.append(model.key)
        return Path(model.file)

    monkeypatch.setattr(mw.models, "NUMBER_MODELS", ())  # the detector alone
    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: model.key in fetched)
    win = make_window()
    assert fetched == []  # off: no network at an offline race's start
    win.analysis_box.setChecked(True)
    wait_until(lambda: fetched == ["yolox_s"])


def test_the_number_reader_is_fetched_once_numbers_and_crossings_are_on(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """006 FR-002: its two models one after the other, then read with."""
    saved = session.load()
    saved["analysis"] = {"on": True, "model": "m.onnx", "crossings": False}
    session.save(saved)
    fetched: list[str] = []
    failing = [True]

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        if failing[0]:
            failing[0] = False
            raise models.FetchError(f"{model.title} cannot be downloaded: offline")
        fetched.append(model.key)
        return Path(model.file)

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: model.key in fetched)
    win = make_window()
    win.poll()
    assert fetched == []  # numbers off: nothing fetched
    win.crossings_box.setChecked(True)
    said = "crossings are suggested without numbers"
    wait_until(lambda: said in win.statusBar().currentMessage())
    win.crossings_box.setChecked(False)
    started = len(analyzers)
    win.crossings_box.setChecked(True)  # tried again
    wait_until(lambda: fetched == ["ppocr_det_en_v3", "ppocr_rec_en_v3"])
    wait_until(lambda: win.statusBar().currentMessage() == "The number reader is ready")
    win.poll()
    assert len(analyzers) > started  # started again, to read numbers


def test_no_number_reader_is_fetched_without_a_detector_to_read_for(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = session.load()
    saved["analysis"] = {"on": True, "model": "", "crossings": True}
    session.save(saved)
    fetched: list[str] = []
    monkeypatch.setattr(
        mw.models, "fetch", lambda model, *a, **k: fetched.append(model.key)
    )
    monkeypatch.setattr(mw.models, "ready", lambda model: False)
    win = make_window()
    win.crossings_box.setChecked(False)
    win.crossings_box.setChecked(True)
    QApplication.processEvents()
    assert fetched == []  # motion only: no crossing to read a number at


def test_a_detector_chosen_brings_the_number_reader_too(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = session.load()
    saved["analysis"] = {"on": True, "model": "", "crossings": False}
    session.save(saved)
    fetched: list[str] = []

    def fetch(model: models.Model, *args: Any, **kwargs: Any) -> Path:
        fetched.append(model.key)
        return Path(model.file)

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: model.key in fetched)
    win = make_window()
    win._set_model("m.onnx")  # Numbers and crossings turned on with it
    wait_until(lambda: fetched == ["ppocr_det_en_v3", "ppocr_rec_en_v3"])


def test_a_closed_window_hears_nothing_from_a_download_still_running(
    win: mw.MainWindow,
) -> None:
    job = models.Download(models.MODELS[0], lambda *a: None, lambda *a: None)
    win._job = job
    win.close()
    win._fetched(job, "")  # an answer queued before the close, delivered after it
    win._fetch_progress(job, 1_000_000)
    QApplication.processEvents()
    assert analysis.settings(session.load())["model"] == ""


def test_closing_the_window_stops_a_download(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = threading.Event()

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        while not cancelled():
            time.sleep(0.01)
        stopped.set()
        raise models.FetchError(f"{model.title}: download stopped")

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: False)
    win._model_chosen(win.model_box.findData(models.MODELS[2].file))
    win.close()
    assert stopped.wait(5)


def test_the_model_list_turns_neither_with_the_wheel_nor_with_the_keys(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mw.models, "fetch", lambda *a, **k: pytest.fail("fetched"))
    box = win.model_box
    assert box.focusPolicy() == Qt.FocusPolicy.NoFocus
    wheel = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(box, wheel)
    assert box.currentText() == "Motion only"
    assert analysis.settings(session.load())["model"] == ""


def test_a_model_preset_is_downloaded_once_then_used(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """002 FR-003: a preset missing is fetched in the background, then chosen; one
    already there is chosen at once."""
    fetched: list[str] = []
    nano = models.MODELS[0]
    gate = threading.Event()

    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        progress(model.size // 2)
        gate.wait(5)
        fetched.append(model.key)
        return Path(model.file)

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: model.key in fetched)
    labels = [win.model_box.itemText(i) for i in range(win.model_box.count())]
    assert labels == [
        "Motion only",
        "YOLOX-Nano, the fastest (4 MB)",
        "YOLOX-Tiny (21 MB)",
        "YOLOX-S, finds the most (36 MB)",
        "Model file...",
    ]
    win._model_chosen(win.model_box.findData(nano.file))
    assert downloading(win) is nano
    line = win.model_box.findData(nano.file)
    wait_until(lambda: win.model_box.itemText(line).endswith(": 2 of 4 MB"))
    assert win._job is not None
    win._fetch_progress(win._job, nano.size)
    assert win.model_box.itemText(line).endswith(": 4 of 4 MB")  # all of it
    said = "Downloading YOLOX-Nano, the fastest (4 MB)..."
    assert win.statusBar().currentMessage() == said  # not covered by progress
    gate.set()
    wait_until(lambda: analysis.settings(session.load())["model"] == nano.file)
    assert fetched == ["yolox_nano"]
    assert win.model_box.isEnabled()
    assert win.model_box.currentText() == nano.label
    assert win.statusBar().currentMessage() == "YOLOX-Nano, the fastest downloaded"
    win._set_model("")
    win._model_chosen(win.model_box.findData(nano.file))  # there now: no download
    assert fetched == ["yolox_nano"]
    assert analysis.settings(session.load())["model"] == nano.file


@pytest.mark.parametrize(
    "failure",
    [
        models.FetchError("YOLOX-S, finds the most cannot be downloaded: offline"),
        ValueError("what nothing expected"),
    ],
)
def test_a_model_that_cannot_be_downloaded_is_said_and_the_choice_stays(
    win: mw.MainWindow, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def fetch(
        model: models.Model,
        progress: Callable[[int], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        raise failure

    monkeypatch.setattr(mw.models, "fetch", fetch)
    monkeypatch.setattr(mw.models, "ready", lambda model: False)
    win._model_chosen(win.model_box.findData(models.MODELS[2].file))
    wait_until(lambda: downloading(win) is None)
    assert "YOLOX-S, finds the most cannot be downloaded" in (
        win.statusBar().currentMessage()
    )
    assert analysis.settings(session.load())["model"] == ""
    assert win.model_box.currentText() == "Motion only"


def stretch_files(base: Path, stretches: list[list[int]]) -> None:
    folder = base / "video" / "cam1"
    line = {"segment": "x", "stretches": stretches}
    (folder / "activity.jsonl").write_text(json.dumps(line) + "\n")
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
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(analyzers[0])  # the one that died is let go
    wait_until(lambda: win.place is not None)
    win.draw_zone()
    win.picture_clicked((0.3, 0.2))
    win.picture_clicked((0.7, 0.9))
    assert not analyzers[1].running
    assert len(analyzers) == 3
    win.edit_line.setChecked(True)  # the line too: the analyser times crossings of it
    win.picture_clicked((0.4, 0.0))
    win.picture_clicked((0.6, 1.0))
    assert not analyzers[2].running
    assert len(analyzers) == 4
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


def test_segments_that_cannot_be_read_are_said(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    win.cameras["cam1"].index.unreadable.append("20000101-000000-0001")
    win.poll()
    assert "; segments that cannot be read: 1" in win.camera_list.item(0).text()


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


def test_numbers_and_crossings_start_every_analyser_again_on_what_it_runs(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mw.models, "ready", lambda model: True)  # nothing to download
    saved = session.load()
    saved["analysis"] = {"on": True, "model": "", "crossings": False}
    session.save(saved)
    win = make_window()
    win.poll()
    started = len(analyzers)
    win.crossings_box.setChecked(True)
    win.poll()
    assert analysis.settings(session.load())["crossings"] is True
    assert len(analyzers) == started  # no model: motion alone either way, left running
    win._set_model("m.onnx")
    win.poll()
    started = len(analyzers)
    win.crossings_box.setChecked(False)
    win.poll()
    assert analysis.model_in_use(session.load()) == ""  # motion alone
    assert len(analyzers) == started + 1  # started again on it
    win.crossings_box.setChecked(True)
    win.poll()
    assert len(analyzers) == started + 2  # and on the model chosen


def test_a_number_reader_come_after_crossings_were_turned_off_restarts_nothing(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = session.load()
    saved["analysis"] = {"on": True, "model": "m.onnx", "crossings": True}
    session.save(saved)
    monkeypatch.setattr(mw.models, "ready", lambda model: True)
    win = make_window()
    win.poll()
    win.session["analysis"]["crossings"] = False  # turned off while it came
    started = len(analyzers)
    job = win._numbers_job = cast(models.Download, object())
    win._numbers_fetched(job, "")
    assert win.statusBar().currentMessage() == "The number reader is ready"
    assert len(analyzers) == started


def suggestions_at(base: Path, camera_id: str, moments: list[int]) -> None:
    """The camera's analyser suggested crossings at these moments."""
    lines = []
    for ms in moments:
        entry = {"id": f"{camera_id}-{ms}", "camera": camera_id, "ms": ms}
        entry |= {
            "model": "m",
            "frames": [["a.mkv", 1, ms - 10], ["a.mkv", 2, ms + 23]],
        }
        lines.append(json.dumps(entry | {"fraction": 0.3}) + "\n")
    (base / "video" / camera_id / "suggestions.jsonl").write_text("".join(lines))


def test_the_suggestions_are_listed_in_the_order_of_their_moments_shown(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    analysis = {"on": True, "model": "m.onnx", "crossings": True}
    session.save({**session.load(), "analysis": analysis})
    suggestions_at(base, "cam1", [FLASH, FLASH + 100])
    suggestions_at(base, "cam2", [FLASH + 120, FLASH + 280])  # 280: with Side's 0
    done = json.dumps({"id": f"cam1-{FLASH}", "done": "dismissed"}) + "\n"
    (base / "video" / "cam1" / "suggestions.done.jsonl").write_text(done)
    win = make_window()
    shown = [win.suggestion_list.item(n).text() for n in range(2)]
    side = scale_time(to_line_scale(FLASH + 100, False)).split(" ")[1]
    assert shown[0].startswith(side)  # Side's 100, Front's 120 with it
    assert shown[1].endswith("(one dismissed with it)")  # Front's 280, after


def test_a_removed_camera_s_suggestions_leave_the_list_with_it(
    two: None,
    make_window: Callable[[], mw.MainWindow],
    base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = {"on": True, "model": "m.onnx", "crossings": True}
    session.save({**session.load(), "analysis": analysis})
    suggestions_at(base, "cam1", [FLASH])
    suggestions_at(base, "cam2", [FLASH + 20])
    win = make_window()
    assert win.suggestion_list.item(0).text().endswith("Side, Front")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes
    )
    win.camera_list.setCurrentRow(1)
    win.remove_camera()  # Front
    assert win.suggestion_list.count() == 1
    assert win.suggestion_list.item(0).text().endswith("Side")


def test_a_crossing_two_cameras_saw_is_one_suggestion_with_the_number_read(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    """006 FR-003: once, at the median camera's moment, decided together; the
    journal names that camera's frames, which give the time written."""
    analysis = {"on": True, "model": "m.onnx", "crossings": True}
    session.save({**session.load(), "analysis": analysis})
    for camera_id, ms in (("cam1", FLASH), ("cam2", FLASH + 20)):
        frames = [["a.mkv", 1, ms - 10], ["a.mkv", 2, ms + 23]]
        entry = {"id": f"{camera_id}-{ms}", "camera": camera_id, "ms": ms}
        entry |= {"model": "m", "frames": frames, "fraction": 0.3}
        entry |= {"number": "27", "number_sure": 0.95}
        folder = base / "video" / camera_id
        (folder / "suggestions.jsonl").write_text(json.dumps(entry) + "\n")
    win = make_window()
    assert win.suggestion_list.count() == 1
    clock = scale_time(to_line_scale(FLASH, False)).split(" ")[1]  # Side's, the earlier
    assert win.suggestion_list.item(0).text() == f"{clock}  Side, Front  no. 27"
    win.suggestion_list.setCurrentRow(0)
    win.accept_suggestion()  # nothing typed: the number read
    out = base / "out.txt"
    expected = f"27#{scale_time(to_line_scale(FLASH, False))}#nextLap#\n"
    assert out.read_text() == expected
    assert win.suggestion_list.count() == 0
    for camera_id in ("cam1", "cam2"):
        done = base / "video" / camera_id / "suggestions.done.jsonl"
        assert "accepted" in done.read_text()
    written = journal(out)[-1]
    assert (written["camera"], written["frames"][0][2]) == ("cam1", FLASH - 10)


def test_a_suggestion_accepted_after_its_camera_was_aligned_is_written_so(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    """The time written follows the camera's offset as it is when accepted."""
    analysis = {"on": True, "model": "m.onnx", "crossings": True}
    session.save({**session.load(), "analysis": analysis})
    frames = [["a.mkv", 1, FLASH - 10], ["a.mkv", 2, FLASH + 23]]
    entry = {"id": f"cam1-{FLASH}", "camera": "cam1", "ms": FLASH}
    entry |= {"model": "m", "frames": frames, "fraction": 0.3}
    (base / "video" / "cam1" / "suggestions.jsonl").write_text(json.dumps(entry) + "\n")
    win = make_window()
    win.suggestion_list.setCurrentRow(0)
    win.cameras["cam1"].settings["offset_ms"] = 400  # aligned since the list was made
    win.number.setText("27")
    win.accept_suggestion()
    written = (base / "out.txt").read_text()
    assert written == f"27#{scale_time(to_line_scale(FLASH + 400, False))}#nextLap#\n"


def test_a_late_camera_s_suggestion_of_a_crossing_decided_is_offered_with_a_word(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    """006 FR-003: another camera's analyser running behind: its suggestion may be
    the same rider or another, so it is offered, with the decision said."""
    analysis = {"on": True, "model": "m.onnx", "crossings": True}
    session.save({**session.load(), "analysis": analysis})

    def suggests(camera_id: str, ms: int) -> None:
        frames = [["a.mkv", 1, ms - 10], ["a.mkv", 2, ms + 23]]
        entry = {"id": f"{camera_id}-{ms}", "camera": camera_id, "ms": ms}
        entry |= {"model": "m", "frames": frames, "fraction": 0.3}
        with (base / "video" / camera_id / "suggestions.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")

    suggests("cam1", FLASH)
    win = make_window()
    win.suggestion_list.setCurrentRow(0)
    win.number.setText("27")
    win.accept_suggestion()
    assert win.suggestion_list.count() == 0
    suggests("cam2", FLASH + 30)  # Front's analyser, minutes behind
    win.poll()
    assert win.suggestion_list.count() == 1
    assert win.suggestion_list.item(0).text().endswith("Front  (one accepted with it)")
    assert not (base / "video" / "cam2" / "suggestions.done.jsonl").exists()
    win.suggestion_list.setCurrentRow(0)
    win.dismiss_suggestion()  # the same rider: the referee says so
    assert win.suggestion_list.count() == 0
    assert len((base / "out.txt").read_text().splitlines()) == 1


def test_a_detector_chosen_turns_numbers_and_crossings_on(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    session.save({**session.load(), "analysis": {"on": True, "model": ""}})
    win = make_window()
    assert not win.crossings_box.isChecked()
    win._set_model("m.onnx")  # chosen for its crossings
    assert win.crossings_box.isChecked()
    assert analysis.settings(session.load())["crossings"] is True
    win.crossings_box.setChecked(False)  # turned off on purpose: said
    said = "Numbers and crossings are off: riders are found by motion alone"
    assert win.suggestion_list.item(0).text() == said
    win._set_model("")  # motion only: the switch left as it is
    assert not win.crossings_box.isChecked()


def test_suggestions_need_a_model(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    session.save({**session.load(), "analysis": {"on": True, "model": ""}})
    suggest(recording, START + 1000)
    win = make_window()
    said = "Numbers and crossings are off: riders are found by motion alone"
    assert win.suggestion_list.item(0).text() == said  # so the list is empty
    win.crossings_box.setChecked(True)
    assert (
        win.suggestion_list.item(0)
        .text()
        .startswith("Suggestions need a detection model: choose one in the model list")
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
    win.output_view.selectRow(0)  # a caliper time offered to the chosen line
    win.statusBar().clearMessage()
    assert win.output is not None
    left = win.output.texts()[1:]
    offered = parse_time(typed)
    assert offered is not None
    win._offer(offered + 1234, output_list.Change("caliper"))
    assert (
        win.statusBar().currentMessage() == "That crossing is no longer in the output"
    )
    assert win.output.texts() == left  # no other crossing took the time


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


def test_a_stopped_analyser_is_not_waited_for_nor_run_beside_the_next(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    analyzers: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mw, "STOP_MS", 50)
    session.save({**session.load(), "analysis": {"on": True, "model": ""}})
    win = make_window()
    analyzers[0].slow = True  # on a long segment: it ends after it
    win._set_model("")  # the analysers started again for the model chosen
    assert analyzers[0].running
    assert len(analyzers) == 1  # never two at once
    wait_until(lambda: analyzers[0].killed)  # it did not end in time
    win.poll()
    assert len(analyzers) == 2


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


def test_a_decoded_frame_is_shown_in_the_window_s_own_thread(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.widgets.camera_view import CameraView

    in_main: list[bool] = []
    real = CameraView.show_image

    def show_image(self: CameraView, image: QImage) -> None:
        in_main.append(threading.current_thread() is threading.main_thread())
        real(self, image)

    monkeypatch.setattr(CameraView, "show_image", show_image)
    make_window()
    wait_until(lambda: bool(in_main))
    assert all(in_main)


def test_a_frame_that_cannot_be_shown_is_said_not_left_as_another(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.decoder import Decoder

    win = make_window()
    view = win.cameras["cam1"].view
    wait_until(showing(win, START + 69 * 33))
    monkeypatch.setattr(Decoder, "decode", lambda self, path, pts: None)
    win.step(-3)
    wait_until(lambda: view.image.isNull())
    assert view.text == "This frame cannot be shown"
    assert not view.waiting
    view.show_image(QImage(16, 9, QImage.Format.Format_RGB888))
    view.show_waiting()
    view.grab()  # dimmed while the next frame is on its way
    assert view.waiting


def test_a_camera_that_did_not_film_the_moment_says_so(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    win = make_window()
    side, front = win.cameras["cam1"], win.cameras["cam2"]
    wait_until(lambda: side.shown is not None)
    win.seek_ms(FLASH - 500)  # Front's clock is ahead: it starts later on this one
    assert front.shown is None
    assert front.view.text == "No frame at this moment"


def test_the_suggestion_chosen_stays_chosen_as_others_arrive(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    session.save({**session.load(), "analysis": {"on": True, "model": "m.onnx"}})
    suggest(recording, START + 1000, START + 2000)
    win = make_window()
    win.suggestion_list.setCurrentRow(1)
    folder = recording / "video" / "cam1"
    with (folder / "suggestions.jsonl").open("a") as f:
        early = {"id": "cam1-500", "camera": "cam1", "ms": START + 500, "model": "m"}
        f.write(json.dumps(early) + "\n")
    win.poll()
    assert win.suggestion_list.count() == 3
    item = win.suggestion_list.currentItem()
    assert item is not None
    assert item.data(Qt.ItemDataRole.UserRole).kept[2]["id"] == f"cam1-{START + 2000}"


def test_a_crossing_written_whose_journal_failed_is_not_written_twice(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.save({**session.load(), "output": "out.txt"})
    win = make_window()
    wait_until(lambda: win.place is not None)

    def held(path: Path, data: bytes) -> None:
        raise OSError("journal held")

    monkeypatch.setattr(output_list, "_append", held)
    win.number.setText("15")
    win.add_crossing()
    assert "the journal cannot take it" in win.statusBar().currentMessage()
    assert win.number.text() == ""  # done: Enter again would add it twice
    assert len((recording / "out.txt").read_text().splitlines()) == 1
    win.output_view.selectRow(0)
    assert win._correct(lambda output: output.set_number(0, "16"))
    assert "Written; the journal" in win.statusBar().currentMessage()


def test_a_line_half_drawn_starts_over_when_another_camera_is_chosen(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    win = make_window()
    wait_until(lambda: win.place is not None)
    win.edit_line.setChecked(True)
    win.picture_clicked((0.4, 0.1))  # one end on Side
    win.picture_clicked((0.6, 0.9), "cam2")  # then Front's picture: its first end
    assert win.drawing == [(0.6, 0.9)]  # both ends from Front's picture now
    assert win.current == "cam2"
    assert "starts over" in win.statusBar().currentMessage()
    assert win.caliper == []
    assert "finish_line" not in session.load()
    win.picture_clicked((0.6, 0.1))
    assert session.load()["finish_line"] == [[0.6, 0.9], [0.6, 0.1]]
    win.statusBar().clearMessage()
    win.picture_clicked((0.2, 0.9), "cam1")  # nothing drawn yet: Side's first end
    assert win.drawing == [(0.2, 0.9)]
    assert win.statusBar().currentMessage() == ""  # nothing was given up
    win.draw_zone()  # a zone given up: that click chose the camera, no more
    win.picture_clicked((0.3, 0.2), "cam2")
    assert win.drawing is None
    assert not win.edit_line.isChecked()


def test_this_camera_only_is_given_up_with_the_edit_mode(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    win = make_window()
    wait_until(lambda: win.place is not None)
    win.edit_line.setChecked(True)
    win.this_camera_only.setChecked(True)
    win.edit_line.setChecked(False)
    assert not win.this_camera_only.isChecked()
    win.edit_line.setChecked(True)  # later, to move the common line
    win.picture_clicked((0.3, 0.0))
    win.picture_clicked((0.3, 1.0))
    assert session.load()["finish_line"] == [[0.3, 0.0], [0.3, 1.0]]


def test_one_finish_line_for_all_cameras_and_a_camera_s_own_kept(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    win = make_window()
    wait_until(lambda: win.place is not None)
    side, front = win.cameras["cam1"], win.cameras["cam2"]
    win.edit_line.setChecked(True)
    win.picture_clicked((0.4, 0.0))
    win.picture_clicked((0.4, 1.0))  # the common line, on Side's picture
    assert win._line(side) == win._line(front) == ((0.4, 0.0), (0.4, 1.0))
    win.camera_list.setCurrentRow(1)
    win.this_camera_only.setChecked(True)
    win.picture_clicked((0.7, 0.0))
    win.picture_clicked((0.7, 1.0))  # Front's own
    assert session.load()["cameras"][1]["own_line"] is True
    win.camera_list.setCurrentRow(0)
    win.this_camera_only.setChecked(False)
    win.picture_clicked((0.3, 0.0))
    win.picture_clicked((0.3, 1.0))  # the common line moved: Front keeps its own
    assert win._line(side) == ((0.3, 0.0), (0.3, 1.0))
    assert win._line(front) == ((0.7, 0.0), (0.7, 1.0))
    win.camera_list.setCurrentRow(1)
    win.picture_clicked((0.5, 0.0))
    win.picture_clicked((0.5, 1.0))  # drawn on Front for all: it follows again
    assert win._line(front) == win._line(side) == ((0.5, 0.0), (0.5, 1.0))
    win.edit_line.setChecked(False)
    wait_until(win._frame_on_screen)
    win.picture_clicked((0.2, 0.5))  # out of the mode: the caliper's point
    assert win.caliper and session.load()["finish_line"] == [[0.5, 0.0], [0.5, 1.0]]


def test_choosing_a_camera_that_did_not_film_the_moment_keeps_the_moment(
    two: None, make_window: Callable[[], mw.MainWindow], base: Path
) -> None:
    win = make_window()
    side, front = win.cameras["cam1"], win.cameras["cam2"]
    wait_until(lambda: side.shown is not None)
    win.seek_ms(FLASH - 400)  # Front has no frame then
    assert front.shown is None
    win.camera_list.setCurrentRow(1)
    assert win.moment == side.index.frame(side.index.nearest(FLASH - 400) or 0).ms
    assert side.shown is not None  # nobody jumped to Front's newest frame
    assert side.index.frame(side.shown).ms < FLASH
    win.step(1)  # from Front's frame nearest the moment
    assert win.place == 1


def test_the_frame_shown_and_its_caliper_point_stay_when_frames_are_sorted_anew(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    win = make_window()
    view = win.cameras["cam1"].view
    wait_until(showing(win, START + 69 * 33))
    win.step(-9)  # frame 60
    wait_until(showing(win, START + 60 * 33))
    win.picture_clicked((0.25, 0.5))
    assert view.marks == [(0.25, 0.5)]
    record(recording, START - 5000, 10)  # an earlier segment, listed late
    win.poll()
    assert win.place == 70
    wait_until(showing(win, START + 60 * 33))
    assert view.marks == [(0.25, 0.5)]


def test_a_frame_asked_for_before_frames_were_sorted_anew_is_not_shown_for_another(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = make_window()
    camera = win.cameras["cam1"]
    asked: list[Any] = []
    monkeypatch.setattr(
        camera.worker, "request", lambda path, pts, tag: asked.append(tag)
    )
    win._set_live(False)
    win._go(68)
    win._go(69)  # frame 69 asked for, still decoding
    on_its_way = asked[-1]
    win._go(59)  # the referee steps on
    record(recording, START - 5000, 10)  # an earlier segment, listed late
    win._refresh()  # frame 59 is at place 69 now
    assert camera.shown == 69
    win._decoded(on_its_way, QImage(8, 8, QImage.Format.Format_RGB888))
    assert camera.view.waiting  # frame 69's picture is not taken for frame 59


def test_a_decision_the_disk_refuses_is_said_and_the_suggestion_still_leaves(
    recording: Path,
    make_window: Callable[[], mw.MainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.save({**session.load(), "analysis": {"on": True, "model": "m.onnx"}})
    suggest(recording, START + 1000)
    win = make_window()
    win.suggestion_list.setCurrentRow(0)
    (recording / "video" / "cam1" / "suggestions.done.jsonl").mkdir()  # cannot append
    win.dismiss_suggestion()
    assert "cannot be kept for a restart" in win.statusBar().currentMessage()
    assert win.suggestion_list.count() == 0


def test_two_riders_timed_in_a_row_with_the_caliper_are_two_crossings(
    bar: Path, make_window: Callable[[], mw.MainWindow], monkeypatch: pytest.MonkeyPatch
) -> None:
    win = make_window()
    wait_until(lambda: win.place == 5)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, text="", **kw: (text, True))
    for number in ("12", "34"):
        win.number.setText(number)
        win.seek_ms(BAR + round(2 * 1000 / 60))  # frame 2
        win.picture_clicked(edge(2))
        win.step(1)
        win.picture_clicked(edge(3))
    numbers = [t.split("#")[0] for t in bar.read_text().splitlines()]
    assert sorted(numbers) == ["12", "34"]  # 34 added, 12's time kept


def test_nothing_is_timed_on_a_frame_still_on_its_way(
    recording: Path, make_window: Callable[[], mw.MainWindow]
) -> None:
    session.save({**session.load(), "output": "out.txt"})
    win = make_window()
    wait_until(showing(win, START + 69 * 33))
    win.view.show_waiting()  # the next frame asked for, the last one dimmed
    win.number.setText("15")
    for timing in (win.add_crossing, win.time_from_frame):
        timing()
        assert win.statusBar().currentMessage().startswith("The frame is still on")
    win.picture_clicked((0.5, 0.5))
    assert win.caliper == []
    assert win.number.text() == "15"
    assert (recording / "out.txt").read_text() == ""


def test_every_button_shows_its_whole_label_at_the_opening_size(
    win: mw.MainWindow,
) -> None:
    win.resize(1000, 700)  # the size app.main opens the window at
    win.show()
    QApplication.processEvents()
    cut = [
        button.text()
        for button in win.findChildren(QPushButton)
        if button.isVisible() and button.width() < button.sizeHint().width()
    ]
    assert cut == []
