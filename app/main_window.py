"""The PhotoFinish main window: layout and wiring. What is not drawing lives in the
Qt-free modules (session, video_index, recorder) and the widgets."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import session
from app.input_follow import InputFollow
from app.interpolation import Point, between, crossing, finish_line
from app.lines import parse_line, parse_time, scale_time, to_epoch, to_line_scale
from app.output_list import Change, OutputList
from app.paths import app_path
from app.recorder import folder_of
from app.recorder.launcher import Watchdog, describe, heartbeat
from app.video_index import VideoIndex
from app.widgets.camera_dialog import CameraDialog
from app.widgets.camera_view import CameraView
from app.widgets.decode_worker import DecodeWorker
from app.widgets.lists import LinesView, input_rows, output_rows
from app.widgets.number_field import NumberField
from app.widgets.timeline import Timeline

POLL_MS = 500


@dataclass
class Camera:
    """A camera of the session: its recording, its recorder, its view, and the
    thread that decodes its frames."""

    settings: dict[str, Any]
    index: VideoIndex
    watchdog: Watchdog
    item: QListWidgetItem
    view: CameraView
    worker: DecodeWorker
    shown: int | None = None  # the frame on its view, in its index
    wanted: tuple[str, int] | None = None  # the frame last asked for

    @property
    def id(self) -> str:
        return str(self.settings["id"])


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PhotoFinish")
        self.session = session.load()
        self.cameras: dict[str, Camera] = {}
        self.current: str | None = None
        self.place: int | None = None  # the frame shown, in the camera's index
        self.live = True
        self.shared_event: tuple[str, int] | None = None  # camera, its moment

        self.placeholder = CameraView()
        self.views = QWidget()
        self.grid = QGridLayout(self.views)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.addWidget(self.placeholder, 0, 0)
        self.drawing: list[Point] | None = None  # the finish line's ends, while drawn
        self.caliper: list[tuple[str, int, Point]] = []  # camera, frame, point
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek_ms)
        self.timeline.picked.connect(self.pick_between)
        self.time_label = QLabel("--:--:--.---")
        self.camera_list = QListWidget()
        self.camera_list.setWordWrap(True)
        self.camera_list.currentRowChanged.connect(self._choose_camera)
        self.number = NumberField()
        self.number.returnPressed.connect(self.add_crossing)
        self.finish = QCheckBox("Finish")
        self.finish.setToolTip("Crossings added are finishes; unchecked, laps")
        self.finish.setChecked(bool(self.session.get("finish_mode")))
        self.finish.toggled.connect(self._finish_mode)
        self.output_button = QPushButton()
        self.output_button.clicked.connect(self.choose_output)
        self.input_button = QPushButton()
        self.input_button.clicked.connect(self.choose_input)
        self.input_view, self.output_view = LinesView(), LinesView()
        self.input_view.picked.connect(self.seek_line)
        self.output_view.picked.connect(self.seek_line)
        self.output: OutputList | None = None
        self.follow: InputFollow | None = None
        self._open_output()

        self.setCentralWidget(self._layout())
        self._shortcuts()
        for camera in self.session["cameras"]:
            self._add(camera)
        if self.cameras:
            self.camera_list.setCurrentRow(0)
        else:
            self._choose_camera(-1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_MS)
        self.poll()

    # -- layout ----------------------------------------------------------------

    def _layout(self) -> QSplitter:
        transport = QHBoxLayout()
        for label, slot in (
            ("<< 1 s", lambda: self.step_ms(-1000)),
            ("< 10", lambda: self.step(-10)),
            ("< 1", lambda: self.step(-1)),
            ("1 >", lambda: self.step(1)),
            ("10 >", lambda: self.step(10)),
            ("1 s >>", lambda: self.step_ms(1000)),
            ("Live", self.go_live),
        ):
            button = QPushButton(label)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(slot)
            transport.addWidget(button)
        transport.addStretch()
        transport.addWidget(self.time_label)
        line_button = QPushButton("Finish line")
        line_button.setToolTip("Click the line's two ends on the picture")
        line_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        line_button.clicked.connect(self.draw_finish_line)
        event_button = QPushButton("Mark event")
        event_button.setToolTip(
            "Mark one moment every camera shows -- a flash, a hand wave -- on each "
            "camera in turn: they are aligned on it"
        )
        event_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        event_button.clicked.connect(self.mark_event)
        timing = QHBoxLayout()
        timing.addWidget(line_button)
        timing.addWidget(event_button)
        timing.addWidget(QLabel("Number"))
        timing.addWidget(self.number, stretch=1)
        timing.addWidget(self.finish)
        timing.addWidget(self.output_button)
        video = QVBoxLayout()
        video.addWidget(self.views, stretch=1)
        video.addWidget(self.timeline)
        video.addLayout(transport)
        video.addLayout(timing)
        left = QWidget()
        left.setLayout(video)

        add, remove = QPushButton("Add..."), QPushButton("Remove")
        add.clicked.connect(self.add_camera)
        remove.clicked.connect(self.remove_camera)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        cameras = QVBoxLayout()
        cameras.addWidget(QLabel("Cameras"))
        cameras.addWidget(self.camera_list)
        cameras.addLayout(buttons)
        copy = QPushButton("Copy to output")
        copy.setToolTip("Apply the chronometer's change of the chosen input line")
        copy.clicked.connect(self.copy_input)
        inputs = QVBoxLayout()
        inputs.addWidget(self.input_button)
        inputs.addWidget(self.input_view)
        inputs.addWidget(copy)
        corrections = QHBoxLayout()
        for label, slot in (
            ("Time from frame", self.time_from_frame),
            ("Type time...", self.type_time),
            ("Number...", self.change_number),
            ("Remove...", self.remove_line),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            corrections.addWidget(button)
        outputs = QVBoxLayout()
        outputs.addWidget(QLabel("Output: the referee's crossings"))
        outputs.addWidget(self.output_view)
        outputs.addLayout(corrections)
        right = QSplitter(Qt.Orientation.Vertical)
        for part in (cameras, inputs, outputs):
            holder = QWidget()
            holder.setLayout(part)
            right.addWidget(holder)
        right.setMinimumWidth(320)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _shortcuts(self) -> None:
        for keys, slot in (
            ("Left", lambda: self.step(-1)),
            ("Right", lambda: self.step(1)),
            ("Shift+Left", lambda: self.step(-10)),
            ("Shift+Right", lambda: self.step(10)),
            ("Ctrl+Left", lambda: self.step_ms(-1000)),
            ("Ctrl+Right", lambda: self.step_ms(1000)),
            ("L", self.go_live),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(slot)

    # -- cameras ---------------------------------------------------------------

    def add_camera(self) -> None:
        dialog = CameraDialog(self, self._free_id(), usb_cameras())
        if dialog.exec() != CameraDialog.DialogCode.Accepted:
            return
        camera = dialog.camera()
        self.session["cameras"].append(camera)
        session.save(self.session)
        self._add(camera)
        self.camera_list.setCurrentRow(self.camera_list.count() - 1)

    def remove_camera(self) -> None:
        camera = self._camera()
        if camera is None:
            return
        name = camera.settings.get("name", camera.id)
        answer = QMessageBox.question(
            self,
            "Remove the camera",
            f"Remove {name}? Its recorder stops; what it recorded stays on disk.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        camera.watchdog.stop()
        camera.worker.stop()
        self.session["cameras"] = [
            c for c in self.session["cameras"] if c.get("id") != camera.id
        ]
        session.save(self.session)
        del self.cameras[camera.id]
        self.grid.removeWidget(camera.view)
        camera.view.deleteLater()
        self._arrange()
        self.camera_list.takeItem(self.camera_list.row(camera.item))
        if not self.cameras:
            self._choose_camera(-1)

    def _add(self, settings: dict[str, Any]) -> None:
        camera_id = str(settings["id"])
        item = QListWidgetItem(str(settings.get("name", camera_id)))
        item.setData(Qt.ItemDataRole.UserRole, camera_id)
        self.camera_list.addItem(item)
        view, worker = CameraView(), DecodeWorker()
        camera = Camera(
            settings,
            VideoIndex(folder_of(camera_id)),
            Watchdog(camera_id),
            item,
            view,
            worker,
        )
        view.clicked.connect(lambda point: self.picture_clicked(point, camera_id))
        worker.decoded.connect(lambda tag, image: self._show(camera, tag, image))
        self.cameras[camera_id] = camera
        self._arrange()
        if settings.get("record", True):
            camera.watchdog.start()
        self._label(camera)

    def _arrange(self) -> None:
        """The cameras' views side by side, as square a grid as they make."""
        views = [camera.view for camera in self.cameras.values()] or [self.placeholder]
        self.placeholder.setVisible(not self.cameras)
        columns = math.ceil(math.sqrt(len(views)))
        for n, view in enumerate(views):
            self.grid.addWidget(view, n // columns, n % columns)

    @property
    def view(self) -> CameraView:
        """The view of the camera chosen, or the one that says to add a camera."""
        camera = self._camera()
        return self.placeholder if camera is None else camera.view

    def _free_id(self) -> str:
        n = 1
        while f"cam{n}" in self.cameras or folder_of(f"cam{n}").exists():
            n += 1
        return f"cam{n}"

    def _choose_camera(self, row: int) -> None:
        """Another camera to step through; the moment shown stays."""
        item = self.camera_list.item(row) if row >= 0 else None
        self.current = (
            None if item is None else str(item.data(Qt.ItemDataRole.UserRole))
        )
        camera = self._camera()
        for other in self.cameras.values():
            other.view.chosen = other is camera
            other.view.update()
        self.place = None if camera is None else camera.shown
        self.timeline.zoomed = False
        if camera is None:
            self.placeholder.show_text("Add a camera")
        elif camera.shown is None:
            camera.view.show_text("No video yet")
        self._refresh(force=True)
        if self.place is not None and not self.live:
            self._go(self.place)

    def _camera(self) -> Camera | None:
        return None if self.current is None else self.cameras.get(self.current)

    # -- the input and the output ----------------------------------------------

    def choose_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "The chronometer's results file", "", "Text (*.txt);;All (*)"
        )
        if not path:
            return
        output = str(self.session.get("output") or "")
        if output and app_path(output).resolve() == app_path(path).resolve():
            self._say("The input cannot be the output file")
            return
        self.session["input"] = path
        session.save(self.session)
        self._open_input()

    def copy_input(self) -> None:
        """ "Copy to output": the chronometer's change of the chosen input line."""
        chosen = self.input_view.chosen()
        if self.follow is None or chosen is None:
            self._say("Choose a changed line of the input first")
            return
        try:
            self.follow.copy(chosen)
        except ValueError:
            self._say("That line is as it was taken")
            return
        except OSError as error:
            self._say(f"The output file cannot be written: {error}")
            return
        self._show_lists()

    def seek_line(self, line_ms: int) -> None:
        """The video at a line's time, through the offsets."""
        epoch = to_epoch(line_ms, bool(self.session.get("summer_time")))
        self.seek_ms(epoch - int(self.session.get("source_offset_ms", 0)))

    def _open_input(self) -> None:
        chosen = str(self.session.get("input") or "")
        self.input_button.setText(f"Input: {chosen}" if chosen else "Input file...")
        self.follow = None
        if chosen and self.output is not None:
            self.follow = InputFollow(app_path(chosen), self.output)
        self._follow_files()
        self._show_lists()

    def _follow_files(self) -> None:
        """New input lines taken; an output file changed outside kept and rewritten."""
        try:
            if self.follow is not None and self.follow.poll():
                self._show_lists()
            if self.output is not None and self.output.check_outside():
                self._say(
                    "The output file was changed outside PhotoFinish: kept beside it"
                )
                self._show_lists()
        except OSError as error:
            self._say(f"The files cannot be followed: {error}")

    def _show_lists(self) -> None:
        self.input_view.show_rows(input_rows(self.follow.lines) if self.follow else [])
        self.output_view.show_rows(
            output_rows(self.output.lines) if self.output else []
        )
        camera = self._camera()
        if camera is not None and self.place is not None:
            self._follow_lists(camera.index.frame(self.place).ms + self._offset())

    def _follow_lists(self, moment: int) -> None:
        line_ms = self._line_ms(moment)
        self.input_view.follow(line_ms)
        self.output_view.follow(line_ms)

    def _line_ms(self, moment: int) -> int:
        """A moment of the video on the timing source's scale."""
        source = int(self.session.get("source_offset_ms", 0))
        return to_line_scale(moment + source, bool(self.session.get("summer_time")))

    def choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "The file the corrected crossings go to", "", "Text (*.txt)"
        )
        if not path:
            return
        if self._same_as_input(path):
            self._say(
                "The output cannot be the chronometer's file: that one is only read"
            )
            return
        self.session["output"] = path
        session.save(self.session)
        self._open_output()

    def add_crossing(self) -> None:
        """A crossing for the typed number at the frame shown."""
        if self.output is None:
            self._say("Choose the output file first")
            return
        timed = self._frame_change()
        if timed is None:
            self._say("There is no frame to time the crossing on")
            return
        line_ms, change = timed
        action = "finish" if self.finish.isChecked() else "nextLap"
        try:
            self.output.add(self.number.text(), line_ms, action, change)
        except ValueError:
            self._say("Type the rider's number first")
            return
        except OSError as error:
            self._say(f"The output file cannot be written: {error}")
            return
        self._say(f"Added {self.number.text().strip()} at {scale_time(line_ms)}")
        self.number.clear()
        self._show_lists()

    def time_from_frame(self) -> None:
        """The chosen output line takes the time of the frame shown."""
        chosen = self._chosen_output()
        timed = self._frame_change()
        if chosen is None:
            return
        if timed is None:
            self._say("There is no frame to take the time from")
            return
        self._correct(lambda output: output.set_time(chosen, *timed))

    def type_time(self) -> None:
        chosen = self._chosen_output()
        if chosen is None or self.output is None:
            return
        fields = self.output.lines[chosen].text.split("#")
        text, ok = QInputDialog.getText(
            self,
            "Type the time",
            "D H:M:S.mmm",
            text=fields[1] if len(fields) > 1 else "",
        )
        if not ok:
            return
        ms = parse_time(text)
        if ms is None:
            self._say(f"{text.strip()!r} is not a time like 20389 11:35:29.615")
            return
        self._correct(lambda output: output.set_time(chosen, ms, Change("typed")))

    def change_number(self) -> None:
        chosen = self._chosen_output()
        if chosen is None or self.output is None:
            return
        number = parse_line(self.output.lines[chosen].text).number
        text, ok = QInputDialog.getText(
            self, "Change the number", "Number", text=number
        )
        if ok:
            self._correct(lambda output: output.set_number(chosen, text))

    def remove_line(self) -> None:
        chosen = self._chosen_output()
        if chosen is None or self.output is None:
            return
        text = self.output.lines[chosen].text
        answer = QMessageBox.question(
            self, "Remove the crossing", f"Remove {text}? The journal keeps it."
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._correct(lambda output: output.remove(chosen))

    # -- the finish line and the caliper ----------------------------------------

    def draw_finish_line(self) -> None:
        """The next two clicks on the picture are the finish line's ends."""
        if self._camera() is None:
            self._say("Add a camera first")
            return
        self.drawing = []
        self._say("Click one end of the finish line, then the other")
        self._show_marks()

    def picture_clicked(self, point: Point, camera_id: str | None = None) -> None:
        """A click on a camera's picture: that camera is chosen, then the click is a
        point of the finish line being drawn or of the caliper."""
        if camera_id is not None and camera_id != self.current:
            self.camera_list.setCurrentRow(list(self.cameras).index(camera_id))
        camera = self._camera()
        if camera is None or self.place is None:
            return
        if self.drawing is None:
            self._caliper(camera, self.place, point)
        else:
            self._draw(camera, self.drawing, point)
        self._show_marks()

    def _draw(self, camera: Camera, drawing: list[Point], point: Point) -> None:
        drawing.append(point)
        if len(drawing) < 2:
            return
        camera.settings["finish_line"] = [list(end) for end in drawing]
        session.save(self.session)
        self.drawing = None
        self._say("The finish line is drawn")

    def _caliper(self, camera: Camera, place: int, point: Point) -> None:
        """A point of the rider on this frame; with one on another frame, the time
        it crossed the line, offered to accept or adjust."""
        others = [c for c in self.caliper if c[0] == camera.id and c[1] != place]
        self.caliper = [*others[-1:], (camera.id, place, point)]
        if len(self.caliper) < 2:
            self._say("Now the same point on a frame on the other side of the line")
            return
        (_, first, a), (_, second, b) = sorted(self.caliper, key=lambda c: c[1])
        fraction = crossing(finish_line(camera.settings.get("finish_line")), a, b)
        if fraction is None:
            self._say(
                "Both points are on one side of the finish line: "
                "PhotoFinish interpolates, it does not extrapolate"
            )
            return
        if not self._has_target():
            return
        frames = [camera.index.frame(first), camera.index.frame(second)]
        moment = between(frames[0].ms, frames[1].ms, fraction) + self._offset()
        change = Change(
            "interpolated",
            camera.id,
            [[f.path.name, f.pts, f.ms] for f in frames],
            round(fraction, 4),
            self._offsets(),
        )
        self.caliper = []
        self._offer(self._line_ms(moment), change)

    def pick_between(self, ms: int) -> None:
        """A moment picked between two frames on the zoomed timeline, offered as a
        time picked by hand between them."""
        camera = self._camera()
        if camera is None or not self._has_target():
            return
        index = camera.index
        after = index.nearest(ms - self._offset())
        if after is None:
            return
        if index.frame(after).ms + self._offset() < ms:
            after += 1
        frames = [index.frame(after - 1), index.frame(after)]
        change = Change(
            "hand",
            camera.id,
            [[f.path.name, f.pts, f.ms] for f in frames],
            None,
            self._offsets(),
        )
        self._offer(self._line_ms(ms), change)

    def _has_target(self) -> bool:
        """An output line chosen, or a number typed, to give a time to."""
        if self.output is not None and (
            self.output_view.chosen() is not None or self.number.text().strip()
        ):
            return True
        self._say("Choose a line of the output or type a number, then click again")
        return False

    def _offer(self, line_ms: int, change: Change) -> None:
        """The time offered, for the referee to accept or adjust; then the chosen
        output line takes it, or a crossing for the typed number does."""
        offered = scale_time(line_ms)
        text, ok = QInputDialog.getText(
            self, "The crossing time", "Accept it, or adjust it first", text=offered
        )
        if not ok:
            return
        ms = parse_time(text)
        if ms is None:
            self._say(f"{text.strip()!r} is not a time like {offered}")
            return
        if ms != line_ms:
            change = Change("typed", change.camera, change.frames, None, change.offsets)
        chosen = self.output_view.chosen()
        if chosen is not None:
            self._correct(lambda output: output.set_time(chosen, ms, change))
            return
        action = "finish" if self.finish.isChecked() else "nextLap"
        number = self.number.text()
        self._correct(lambda output: output.add(number, ms, action, change))
        self.number.clear()

    def _show_marks(self) -> None:
        """Each view: its camera's finish line, the points clicked on its frame."""
        for camera in self.cameras.values():
            marks = [
                p
                for c, place, p in self.caliper
                if c == camera.id and place == camera.shown
            ]
            if camera.id == self.current:
                marks += self.drawing or []
            line = finish_line(camera.settings.get("finish_line"))
            camera.view.show_marks(line, marks)

    def _offsets(self) -> dict[str, int]:
        return {
            "camera_ms": self._offset(),
            "source_ms": int(self.session.get("source_offset_ms", 0)),
        }

    def _chosen_output(self) -> int | None:
        chosen = self.output_view.chosen()
        if self.output is None or chosen is None:
            self._say("Choose a line of the output first")
            return None
        return chosen

    def _correct(self, change: Callable[[OutputList], object]) -> None:
        """One change of the output, shown, the line it moved to chosen."""
        if self.output is None:
            return
        try:
            moved = change(self.output)
        except ValueError:
            self._say("A crossing needs a number")
            return
        except OSError as error:
            self._say(f"The output file cannot be written: {error}")
            return
        self._show_lists()
        if isinstance(moved, int):
            self.output_view.selectRow(moved)
        else:
            self.output_view.clearSelection()

    def _frame_change(self) -> tuple[int, Change] | None:
        """The frame shown as a time on the line scale, and how it was had."""
        camera = self._camera()
        if camera is None or self.place is None:
            return None
        frame = camera.index.frame(self.place)
        line_ms = self._line_ms(frame.ms + self._offset())
        frames = [[frame.path.name, frame.pts, frame.ms]]
        return line_ms, Change("frame", camera.id, frames, None, self._offsets())

    def _open_output(self) -> None:
        chosen = str(self.session.get("output") or "")
        self.output_button.setText(f"Output: {chosen}" if chosen else "Output file...")
        self.output = None
        if chosen:
            try:
                self.output = OutputList(app_path(chosen))
            except OSError as error:
                self._say(f"The output file cannot be opened: {error}")
        self._open_input()

    def _same_as_input(self, path: str) -> bool:
        chosen = str(self.session.get("input") or "")
        return bool(chosen) and app_path(chosen).resolve() == app_path(path).resolve()

    def _finish_mode(self, on: bool) -> None:
        self.session["finish_mode"] = on
        session.save(self.session)

    def _say(self, text: str) -> None:
        self.statusBar().showMessage(text, 8000)

    # -- moving through the video ----------------------------------------------

    def poll(self) -> None:
        for camera in self.cameras.values():
            self._label(camera)
        self._follow_files()
        self._refresh()

    def _label(self, camera: Camera) -> None:
        """The camera's line in the list: its name and how its recorder is."""
        watchdog = camera.watchdog
        info = (watchdog.poll() if watchdog.wanted else None) or heartbeat(camera.id)
        if info is not None:
            state = describe(info)
        else:
            state = "starting" if watchdog.wanted else "not recording"
        camera.item.setText(f"{camera.settings.get('name', camera.id)}: {state}")

    def step(self, frames: int) -> None:
        camera = self._camera()
        if camera is not None and self.place is not None:
            self._leave_live()
            self._go(camera.index.step(self.place, frames))

    def step_ms(self, ms: int) -> None:
        camera = self._camera()
        if camera is not None and self.place is not None:
            self._leave_live()
            self._go(camera.index.step_ms(self.place, ms))

    def seek_ms(self, ms: int) -> None:
        camera = self._camera()
        place = None if camera is None else camera.index.nearest(ms - self._offset())
        if place is not None:
            self._leave_live()
            self._go(place)

    def go_live(self) -> None:
        self.live = True
        self.timeline.following = True
        camera = self._camera()
        if camera is not None and len(camera.index):
            self._go(len(camera.index) - 1)

    def _leave_live(self) -> None:
        self.live = False
        self.timeline.following = False

    def _refresh(self, force: bool = False) -> None:
        grown = [other.index.refresh() for other in self.cameras.values()]
        camera = self._camera()
        if camera is None:
            self.timeline.set_recording(np.empty(0, np.int64), [])
            return
        if not any(grown) and not force:
            return
        offset = self._offset()
        gaps = [(g.start_ms + offset, g.end_ms + offset) for g in camera.index.gaps]
        self.timeline.set_recording(camera.index.ms + offset, gaps)
        if len(camera.index) and (self.live or self.place is None):
            self._go(len(camera.index) - 1)

    def _go(self, place: int) -> None:
        camera = self._camera()
        if camera is None:
            return
        self.place = place
        frame = camera.index.frame(place)
        moment = frame.ms + self._offset()
        self.timeline.set_position(moment)
        clock = scale_time(self._line_ms(moment)).split(" ")[1]
        self.time_label.setText(f"{clock} LIVE" if self.live else clock)
        self._follow_lists(moment)
        for other in self.cameras.values():
            self._show_at(other, place if other is camera else None, moment)
        self._show_marks()

    def _show_at(self, camera: Camera, place: int | None, moment: int) -> None:
        """The camera's frame at ``place``, or else its frame nearest ``moment``."""
        if place is None:
            offset = int(camera.settings.get("offset_ms", 0))
            place = camera.index.nearest(moment - offset)
        camera.shown = place
        if place is None or (camera.id, place) == camera.wanted:
            return
        camera.wanted = (camera.id, place)
        frame = camera.index.frame(place)
        camera.worker.request(frame.path, frame.pts, camera.wanted)

    def _show(self, camera: Camera, tag: tuple[str, int], image: QImage) -> None:
        if tag == camera.wanted and not image.isNull():
            camera.view.show_image(image)

    # -- cameras in step -------------------------------------------------------

    def mark_event(self) -> None:
        """The shared event at the frame shown. The first camera it is marked on
        sets its moment; each camera marked after takes the offset that shows the
        event at that moment."""
        camera = self._camera()
        if camera is None or self.place is None:
            self._say("Show the event on a camera first")
            return
        name = camera.settings.get("name", camera.id)
        frame = camera.index.frame(self.place)
        if self.shared_event is None or self.shared_event[0] == camera.id:
            self.shared_event = (camera.id, frame.ms + self._offset())
            self._say(f"Event marked on {name}: now show it on the other cameras")
            return
        offset = self.shared_event[1] - frame.ms
        camera.settings["offset_ms"] = offset
        session.save(self.session)
        self._say(f"{name} is aligned on the event: {offset:+d} ms")
        self._refresh(force=True)
        self._go(self.place)

    def _offset(self) -> int:
        camera = self._camera()
        return 0 if camera is None else int(camera.settings.get("offset_ms", 0))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's name
        """The window goes; the recorders keep recording."""
        self.timer.stop()
        for camera in self.cameras.values():
            camera.worker.stop()
        super().closeEvent(event)


def usb_cameras() -> list[str]:
    """The names of the cameras on this computer, as the system lists them."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
    except ImportError:  # pragma: no cover - a Qt without multimedia
        return []
    return [device.description() for device in QMediaDevices.videoInputs()]
