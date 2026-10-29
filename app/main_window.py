"""The PhotoFinish main window: layout and wiring. What is not drawing lives in the
Qt-free modules (session, video_index, recorder) and the widgets."""

from __future__ import annotations

import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
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

from app import analysis, paths, session
from app.analysis.activity import Activity
from app.analysis.suggestions import Suggestions
from app.input_follow import InputFollow
from app.interpolation import Point, between, crossing, finish_line, points
from app.lines import (
    parse_line,
    parse_time,
    scale_time,
    source_offset,
    to_epoch,
    to_line_scale,
)
from app.output_list import Change, JournalError, OutputLine, OutputList
from app.paths import app_path
from app.recorder import folder_of
from app.recorder.launcher import Watchdog, command, describe, heartbeat, package_root
from app.video_index import FileIndex, Frame, VideoIndex
from app.widgets.camera_dialog import CameraDialog
from app.widgets.camera_view import CameraView
from app.widgets.decode_worker import DecodeWorker
from app.widgets.lists import LinesView, input_rows, output_rows
from app.widgets.number_field import NumberField
from app.widgets.timeline import Timeline

POLL_MS = 500
NEAR_MS = 1000  # another camera's frame further from the moment than this: none
STOP_MS = 3000  # an analyser stopped is killed if it has not ended by then
EVENT_S = 600  # a shared event not shown on the other cameras by then is forgotten


@dataclass
class SharedEvent:
    """An event marked on one camera, for the other cameras to be aligned on."""

    camera: str
    moment: int  # on the video's time
    since: float  # monotonic
    aligned: set[str] = field(default_factory=set)


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
    activity: Activity
    suggestions: Suggestions
    shown: int | None = None  # the frame on its view, in its index
    wanted: tuple[str, int] | None = None  # the frame last asked for
    analyzer: Any = None  # its analyser process, while finding riders is on
    analyzer_started: float = -math.inf  # monotonic
    stopping: Any = None  # the analyser stopped, while it ends its segment

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
        self.moment: int | None = None  # the video's time shown, ms
        self.live = True
        self.shared_event: SharedEvent | None = None

        self.placeholder = CameraView()
        self.views = QWidget()
        self.grid = QGridLayout(self.views)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.addWidget(self.placeholder, 0, 0)
        self.drawing: list[Point] | None = None  # the ends of what is drawn
        self.drawn = "finish_line"  # what it is: the finish line or the zone
        self.caliper: list[tuple[str, Frame, Point]] = []  # camera, frame, point
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek_ms)
        self.timeline.picked.connect(self.pick_between)
        self.time_label = QLabel("--:--:--.---")
        self.source_label = QLabel()
        self.source_label.setToolTip(
            "Added to the video's time to give the timing source's: set with "
            "'Align with source'"
        )
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
        self.analysis_box = QCheckBox("Find riders (experimental)")
        self.analysis_box.setChecked(analysis.settings(self.session)["on"])
        self.analysis_box.toggled.connect(self._analysis_on)
        self.model_button = QPushButton()
        self.model_button.clicked.connect(self.choose_model)
        self._show_model()
        self.suggestion_list = QListWidget()
        self.suggestion_list.itemClicked.connect(self._suggestion_picked)

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
        self._show_suggestions()

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
        transport.addWidget(self.source_label)
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
        zone_button = QPushButton("Zone")
        zone_button.setToolTip("Click two corners of where riders pass the line")
        zone_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        zone_button.clicked.connect(self.draw_zone)
        motion_only = QPushButton("Motion only")
        motion_only.setToolTip("Find riders by motion, without a model")
        motion_only.clicked.connect(lambda: self._set_model(""))
        previous_rider = QPushButton("< Previous rider")
        previous_rider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        previous_rider.clicked.connect(self.previous_rider)
        next_rider = QPushButton("Next rider >")
        next_rider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        next_rider.clicked.connect(self.next_rider)
        finding = QHBoxLayout()
        finding.addWidget(previous_rider)
        finding.addWidget(next_rider)
        finding.addWidget(self.analysis_box)
        finding.addWidget(zone_button)
        finding.addWidget(self.model_button)
        finding.addWidget(motion_only)
        finding.addStretch()
        video = QVBoxLayout()
        video.addWidget(self.views, stretch=1)
        video.addWidget(self.timeline)
        video.addLayout(transport)
        video.addLayout(timing)
        video.addLayout(finding)
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
        align = QPushButton("Align with source")
        align.setToolTip(
            "The chosen input line and the frame shown are the same passing: the "
            "video is aligned with the timing source on it"
        )
        align.clicked.connect(self.align_source)
        input_buttons = QHBoxLayout()
        input_buttons.addWidget(copy)
        input_buttons.addWidget(align)
        inputs = QVBoxLayout()
        inputs.addWidget(self.input_button)
        inputs.addWidget(self.input_view)
        inputs.addLayout(input_buttons)
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
        accept = QPushButton("Accept with the number")
        accept.setToolTip("Type the rider's number, then accept the crossing suggested")
        accept.clicked.connect(self.accept_suggestion)
        dismiss = QPushButton("Dismiss")
        dismiss.clicked.connect(self.dismiss_suggestion)
        decide = QHBoxLayout()
        decide.addWidget(accept)
        decide.addWidget(dismiss)
        suggested = QVBoxLayout()
        suggested.addWidget(QLabel("Suggested crossings (experimental)"))
        suggested.addWidget(self.suggestion_list)
        suggested.addLayout(decide)
        right = QSplitter(Qt.Orientation.Vertical)
        for part in (cameras, inputs, outputs, suggested):
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
            ("End", self.go_live),
            ("L", self.go_live),  # when no number is being typed
            ("PgUp", self.previous_rider),
            ("PgDown", self.next_rider),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(slot)

    # -- cameras ---------------------------------------------------------------

    def add_camera(self) -> None:
        dialog = CameraDialog(self, self._free_id(), usb_cameras())
        if dialog.exec() != CameraDialog.DialogCode.Accepted:
            return
        camera = dialog.camera()
        self.session["cameras"].append(camera)
        self._save_session()
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
        self._stop_analyzer(camera)
        self.session["cameras"] = [
            c for c in self.session["cameras"] if c.get("id") != camera.id
        ]
        self._save_session()
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
        recorded = settings.get("record", True) or settings.get("connection") != "file"
        index = (
            VideoIndex(folder_of(camera_id))
            if recorded
            else FileIndex(app_path(str(settings["settings"]["path"])))
        )
        camera = Camera(
            settings,
            index,
            Watchdog(camera_id),
            item,
            view,
            worker,
            Activity(folder_of(camera_id)),
            Suggestions(folder_of(camera_id)),
        )
        view.clicked.connect(lambda point: self.picture_clicked(point, camera_id))
        worker.decoded.connect(self._decoded)  # a window's method: in its thread
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
        """Another camera to step through; the moment shown stays. A line or zone
        half drawn is given up: its ends must come from one camera's picture."""
        if self.drawing is not None:
            self.drawing = None
            self._say("Drawing stopped: click both ends on one camera's picture")
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
        self._refresh(force=True)  # the frame at the moment, or the newest when live

    def _camera(self) -> Camera | None:
        return None if self.current is None else self.cameras.get(self.current)

    # -- the input and the output ----------------------------------------------

    def choose_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "The chronometer's results file", "", "Text (*.txt);;All (*)"
        )
        if not path:
            return
        if _same_file(self.session.get("output"), path):
            self._say("The input cannot be the output file")
            return
        self.session["input"] = path
        self._save_session()
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
        except JournalError as error:
            self._say(f"Copied; the journal cannot take it: {error}")
        except OSError as error:
            self._say(f"The output file cannot be written: {error}")
            return
        self._show_lists()

    def align_source(self) -> None:
        """The chosen input line and the frame shown are the same passing: the
        offset between the timing source and the video, kept and used both ways --
        input lines open shifted by it, times set from frames are written back."""
        camera = self._camera()
        chosen = self.input_view.chosen()
        if camera is None or self.place is None:
            self._say("Show the frame of the passing first")
            return
        if self.follow is None or chosen is None:
            self._say("Choose the input line of the passing first")
            return
        line_ms = parse_line(self.follow.lines[chosen].text).ms
        if line_ms is None:
            self._say("That line has no time to align on")
            return
        moment = camera.index.frame(self.place).ms + self._offset()
        offset = source_offset(line_ms, moment, bool(self.session.get("summer_time")))
        self.session["source_offset_ms"] = offset
        self._save_session()
        self._say(f"The video is aligned with the timing source: {offset:+d} ms")
        self._go(self.place)

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
        except (
            JournalError
        ) as error:  # lines taken, or an outside version kept: written
            self._say(f"Written; the journal cannot take it: {error}")
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
        if _same_file(self.session.get("input"), path):
            self._say(
                "The output cannot be the chronometer's file: that one is only read"
            )
            return
        self.session["output"] = path
        self._save_session()
        self._open_output()

    def add_crossing(self) -> None:
        """A crossing for the typed number at the frame shown."""
        if self.output is None:
            self._say("Choose the output file first")
            return
        if not self._frame_on_screen():
            return
        timed = self._frame_change()
        if timed is None:
            self._say("There is no frame to time the crossing on")
            return
        line_ms, change = timed
        said = f"Added {self.number.text().strip()} at {scale_time(line_ms)}"
        try:
            self.output.add(self.number.text(), line_ms, self._action(), change)
        except ValueError:
            self._say("Type the rider's number first")
            return
        except JournalError as error:
            said += f"; the journal cannot take it: {error}"
        except OSError as error:
            self._say(f"The output file cannot be written: {error}")
            return
        self._say(said)
        self.number.clear()
        self._show_lists()

    def time_from_frame(self) -> None:
        """The chosen output line takes the time of the frame shown."""
        if not self._frame_on_screen():
            return
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
        line = self.output.lines[chosen]  # lines may move while the dialog is open
        fields = line.text.split("#")
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
        index = self._index_of(line)
        if index is not None:
            self._correct(lambda output: output.set_time(index, ms, Change("typed")))

    def change_number(self) -> None:
        chosen = self._chosen_output()
        if chosen is None or self.output is None:
            return
        line = self.output.lines[chosen]
        number = parse_line(line.text).number
        text, ok = QInputDialog.getText(
            self, "Change the number", "Number", text=number
        )
        index = self._index_of(line) if ok else None
        if index is not None:
            self._correct(lambda output: output.set_number(index, text))

    def remove_line(self) -> None:
        chosen = self._chosen_output()
        if chosen is None or self.output is None:
            return
        line = self.output.lines[chosen]
        answer = QMessageBox.question(
            self, "Remove the crossing", f"Remove {line.text}? The journal keeps it."
        )
        yes = answer == QMessageBox.StandardButton.Yes
        index = self._index_of(line) if yes else None
        if index is not None:
            self._correct(lambda output: output.remove(index))

    def _index_of(self, line: OutputLine) -> int | None:
        """Where a line is in the output now: the list may have moved under a dialog."""
        lines = [] if self.output is None else self.output.lines
        found = next((i for i, other in enumerate(lines) if other is line), None)
        if found is None:
            self._say("That crossing is no longer in the output")
        return found

    # -- the finish line and the caliper ----------------------------------------

    def draw_finish_line(self) -> None:
        """The next two clicks on the picture are the finish line's ends."""
        self._start_drawing(
            "finish_line", "Click one end of the finish line, then the other"
        )

    def draw_zone(self) -> None:
        """The next two clicks on the picture are corners of the zone where riders
        pass the line: motion elsewhere is not looked at."""
        self._start_drawing(
            "zone", "Click one corner of the zone, then the opposite one"
        )

    def _start_drawing(self, what: str, say: str) -> None:
        if self._camera() is None:
            self._say("Add a camera first")
            return
        self.drawing, self.drawn = [], what
        self._say(say)
        self._show_marks()

    def picture_clicked(self, point: Point, camera_id: str | None = None) -> None:
        """A click on a camera's picture: that camera is chosen, then the click is a
        point of the finish line being drawn or of the caliper."""
        if camera_id is not None and camera_id != self.current:
            drawing = self.drawing is not None
            self.camera_list.setCurrentRow(list(self.cameras).index(camera_id))
            if drawing:
                return  # the drawing was stopped: this click chose the camera
        camera = self._camera()
        if camera is None or self.place is None:
            return
        if self.drawing is None:
            if not self._frame_on_screen():
                return
            self._caliper(camera, camera.index.frame(self.place), point)
        else:
            self._draw(camera, self.drawing, point)
        self._show_marks()

    def _draw(self, camera: Camera, drawing: list[Point], point: Point) -> None:
        drawing.append(point)
        if len(drawing) < 2:
            return
        zone = self.drawn == "zone"
        if not (analysis.valid_zone(drawing) if zone else points(drawing)):
            drawing.pop()  # a double click, say: the first end stays, the other asked
            self._say(
                "Click the opposite corner: the zone needs width and height"
                if zone
                else "Click the other end of the line, apart from the first"
            )
            return
        camera.settings[self.drawn] = [list(end) for end in drawing]
        self._save_session()
        if self.analysis_box.isChecked():  # the new line or zone from here on
            self._stop_analyzer(camera)
            self._analyze(camera)
        self.drawing = None
        self._say(
            "The zone is drawn" if self.drawn == "zone" else "The finish line is drawn"
        )

    def _caliper(self, camera: Camera, frame: Frame, point: Point) -> None:
        """A point of the rider on this frame; with one on another frame, the time
        it crossed the line, offered to accept or adjust. Points keep their frames,
        not their places in the index, which a late segment can move."""
        others = [c for c in self.caliper if c[0] == camera.id and c[1] != frame]
        self.caliper = [*others[-1:], (camera.id, frame, point)]
        if len(self.caliper) < 2:
            self._say("Now the same point on a frame on the other side of the line")
            return
        (_, first, a), (_, second, b) = sorted(self.caliper, key=lambda c: c[1].ms)
        fraction = crossing(finish_line(camera.settings.get("finish_line")), a, b)
        if fraction is None:
            self._say(
                "Both points are on one side of the finish line: "
                "PhotoFinish interpolates, it does not extrapolate"
            )
            return
        if not self._has_target():
            return
        frames = [first, second]
        moment = between(first.ms, second.ms, fraction) + self._offset()
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
        around = camera.index.around(ms - self._offset())
        if around is None:
            return
        frames = [camera.index.frame(place) for place in around]
        change = Change(
            "hand",
            camera.id,
            [[f.path.name, f.pts, f.ms] for f in frames],
            None,
            self._offsets(),
        )
        self._offer(self._line_ms(ms), change)

    def _frame_on_screen(self) -> bool:
        """False, said, while the frame stepped to is still on its way: the picture
        on screen is the one before, and timing on it would time another frame."""
        if self.view.waiting:
            self._say("The frame is still on its way: try again in a moment")
            return False
        return True

    def _has_target(self) -> bool:
        """A number typed, or an output line chosen, to give a time to."""
        if self.output is not None and (
            self.output_view.chosen() is not None or self.number.text().strip()
        ):
            return True
        self._say("Choose a line of the output or type a number, then click again")
        return False

    def _offer(self, line_ms: int, change: Change) -> None:
        """The time offered, for the referee to accept or adjust; then a crossing
        for the typed number takes it, or, with no number typed, the chosen output
        line does. The number first: a line added stays chosen, and the next rider
        must not take its time."""
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
        action, number = self._action(), self.number.text()
        if number.strip():
            if self._correct(lambda output: output.add(number, ms, action, change)):
                self.number.clear()
            return
        chosen = self.output_view.chosen()
        if chosen is not None:
            self._correct(lambda output: output.set_time(chosen, ms, change))

    def _show_marks(self) -> None:
        """Each view: its camera's finish line, the points clicked on its frame."""
        for camera in self.cameras.values():
            shown = None if camera.shown is None else camera.index.frame(camera.shown)
            marks = [
                p for c, frame, p in self.caliper if c == camera.id and frame == shown
            ]
            if camera.id == self.current:
                marks += self.drawing or []
            line = finish_line(camera.settings.get("finish_line"))
            on = self.analysis_box.isChecked()
            camera.view.show_marks(
                line, marks, analysis.zone(camera.settings) if on else None
            )

    # -- finding riders (experimental) -------------------------------------------

    def choose_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "A detection model, downloaded beforehand", "", "ONNX model (*.onnx)"
        )
        if path:
            self._set_model(path)

    def _set_model(self, path: str) -> None:
        self.session["analysis"] = {**analysis.settings(self.session), "model": path}
        self._save_session()
        self._show_model()
        self._show_suggestions()
        if self.analysis_box.isChecked():  # the model chosen from here on
            for camera in self.cameras.values():
                self._stop_analyzer(camera)
                self._analyze(camera)

    def _show_model(self) -> None:
        model = analysis.settings(self.session)["model"]
        self.model_button.setText(f"Model: {Path(model).name}" if model else "Model...")

    def _analysis_on(self, on: bool) -> None:
        self.session["analysis"] = {**analysis.settings(self.session), "on": on}
        self._save_session()
        for camera in self.cameras.values():
            if on:
                self._analyze(camera)
            else:
                self._stop_analyzer(camera)
        self._show_marks()
        self._show_suggestions()
        self.poll()

    def next_rider(self) -> None:
        self._rider(after=True)

    def previous_rider(self) -> None:
        self._rider(after=False)

    def _rider(self, after: bool) -> None:
        """The video at the start of the next or previous stretch with a rider."""
        camera = self._camera()
        if not self.analysis_box.isChecked():
            self._say("Turn on finding riders first")
            return
        if camera is None or self.place is None:
            return
        ms = camera.index.frame(self.place).ms
        activity = camera.activity
        found = activity.next_after(ms) if after else activity.previous_before(ms)
        if found is None:
            self._say("No rider after this moment" if after else "No rider before this")
            return
        self.seek_ms(found + self._offset())

    def _analyze(self, camera: Camera) -> None:
        """The camera's analyser running, started again 30 s after it last was; not
        beside the one stopped before, while that ends its segment."""
        recorded = camera.settings.get("record", True)
        running = any(
            process is not None and process.state() != QProcess.ProcessState.NotRunning
            for process in (camera.analyzer, camera.stopping)
        )
        failed = (camera.activity.progress or {}).get("state") == "failed"
        waited = time.monotonic() - camera.analyzer_started < 30
        if not recorded or running or waited or (failed and camera.analyzer):
            return
        for ended in (camera.analyzer, camera.stopping):
            if ended is not None:
                ended.deleteLater()  # not kept: one that crashes is restarted all day
        camera.analyzer, camera.stopping = start_analyzer(camera.id, self), None
        camera.analyzer_started = time.monotonic()

    def _stop_analyzer(self, camera: Camera) -> None:
        """Its standard input closed, the analyser ends after the segment it is on;
        killed if it has not in STOP_MS. The window does not wait for it."""
        process, camera.analyzer = camera.analyzer, None
        camera.analyzer_started = -math.inf
        if process is None:
            return
        if process.state() == QProcess.ProcessState.NotRunning:
            process.deleteLater()
            return
        process.closeWriteChannel()
        QTimer.singleShot(STOP_MS, process, process.kill)
        camera.stopping = process  # none before: _analyze cleared it to start this one

    def accept_suggestion(self) -> None:
        """The crossing suggested, with the typed number, through the output's
        usual path; the journal names the model that suggested it."""
        chosen = self._suggestion()
        if chosen is None:
            return
        camera, found = chosen
        if self.output is None or not self.number.text().strip():
            self._say("Type the rider's number first; the output file must be chosen")
            return
        offsets = self._offsets(camera)
        line_ms = self._line_ms(int(found["ms"]) + offsets["camera_ms"])
        change = Change(
            "interpolated",
            camera.id,
            found.get("frames", []),
            found.get("fraction"),
            offsets,
            str(found.get("model", "")),
        )
        number, action = self.number.text(), self._action()
        if not self._correct(
            lambda output: output.add(number, line_ms, action, change)
        ):
            return  # not written: the suggestion stays offered, the number typed
        self.number.clear()
        self._decide(camera, found, "accepted")

    def dismiss_suggestion(self) -> None:
        chosen = self._suggestion()
        if chosen is not None:
            self._decide(*chosen, "dismissed")

    def _decide(self, camera: Camera, found: dict[str, Any], how: str) -> None:
        """A suggestion decided leaves the list; a decision the disk refuses is said:
        offered again after a restart, it would be accepted twice."""
        try:
            camera.suggestions.decide(str(found["id"]), how)
        except OSError as error:
            self._say(f"Done; the decision cannot be kept for a restart: {error}")
        self._show_suggestions()

    def _suggestion(self) -> tuple[Camera, dict[str, Any]] | None:
        item = self.suggestion_list.currentItem()
        data = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        if not data or data[0] not in self.cameras:
            self._say("Choose a suggested crossing first")
            return None
        return self.cameras[data[0]], data[1]

    def _suggestion_picked(self, item: QListWidgetItem) -> None:
        """The video at the suggested moment, on the camera that suggested it."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data[0] not in self.cameras:
            return
        camera_id, found = data
        self.camera_list.setCurrentRow(list(self.cameras).index(camera_id))
        self.seek_ms(int(found["ms"]) + self._offset())

    def _show_suggestions(self) -> None:
        """The crossings suggested and not decided, in time order; the one chosen
        stays chosen."""
        item = self.suggestion_list.currentItem()
        data = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        chosen = data[1].get("id") if data else None
        self.suggestion_list.clear()
        settings = analysis.settings(self.session)
        if not settings["on"]:
            return
        if not settings["model"]:
            hint = QListWidgetItem("Suggestions need a detection model: Model...")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self.suggestion_list.addItem(hint)
            return
        found = [
            (int(s["ms"]) + int(c.settings.get("offset_ms", 0)), c, s)
            for c in self.cameras.values()
            for s in c.suggestions.pending()
        ]
        for moment, camera, suggestion in sorted(found, key=lambda f: f[0]):
            clock = scale_time(self._line_ms(moment)).split(" ")[1]
            name = camera.settings.get("name", camera.id)
            item = QListWidgetItem(f"{clock}  {name}")
            item.setToolTip(f"Suggested by {suggestion.get('model')}")
            item.setData(Qt.ItemDataRole.UserRole, (camera.id, suggestion))
            self.suggestion_list.addItem(item)
            if chosen is not None and suggestion.get("id") == chosen:
                self.suggestion_list.setCurrentItem(item)

    def _action(self) -> str:
        return "finish" if self.finish.isChecked() else "nextLap"

    def _offsets(self, camera: Camera | None = None) -> dict[str, int]:
        camera = camera or self._camera()
        own = 0 if camera is None else int(camera.settings.get("offset_ms", 0))
        return {
            "camera_ms": own,
            "source_ms": int(self.session.get("source_offset_ms", 0)),
        }

    def _chosen_output(self) -> int | None:
        chosen = self.output_view.chosen()
        if self.output is None or chosen is None:
            self._say("Choose a line of the output first")
            return None
        return chosen

    def _correct(self, change: Callable[[OutputList], object]) -> bool:
        """One change of the output, shown, the line it moved to chosen; True when
        it was written."""
        if self.output is None:
            return False
        try:
            moved = change(self.output)
        except ValueError:
            self._say("A crossing needs a number")
            return False
        except JournalError as error:  # written: done, whatever the journal says
            self._say(f"Written; the journal cannot take it: {error}")
            moved = None
        except OSError as error:
            self._say(f"The output file cannot be written: {error}")
            return False
        self._show_lists()
        if isinstance(moved, int):
            self.output_view.selectRow(moved)
        else:
            self.output_view.clearSelection()
        return True

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
            else:
                refused = self.output.journal_error
                if refused is not None:
                    self._say(f"Opened; the journal cannot take it: {refused}")
        self._open_input()

    def _finish_mode(self, on: bool) -> None:
        self.session["finish_mode"] = on
        self._save_session()

    def _save_session(self) -> None:
        """The session on disk; a disk that refuses it is said, the window goes on."""
        try:
            session.save(self.session)
        except OSError as error:
            self._say(f"The session cannot be saved: {error}")

    def _say(self, text: str) -> None:
        self.statusBar().showMessage(text, 8000)

    # -- moving through the video ----------------------------------------------

    def poll(self) -> None:
        finding = self.analysis_box.isChecked()
        suggested = False
        for camera in self.cameras.values():
            if finding:
                camera.activity.refresh()  # its progress first: a failed one waits
                suggested = camera.suggestions.refresh() or suggested
                self._analyze(camera)
            self._label(camera)
        if suggested:
            self._show_suggestions()
        self._follow_files()
        self._refresh()
        current = self._camera()
        stretches = current.activity.stretches if current and finding else []
        offset = self._offset()
        self.timeline.set_stretches([(a + offset, b + offset) for a, b in stretches])

    def _label(self, camera: Camera) -> None:
        """The camera's line in the list: its name and how its recorder is."""
        watchdog = camera.watchdog
        info = (watchdog.poll() if watchdog.wanted else None) or heartbeat(camera.id)
        if info is not None:
            state = describe(info)
        else:
            state = "starting" if watchdog.wanted else "not recording"
        if camera.index.unreadable:
            state += f"; segments that cannot be read: {len(camera.index.unreadable)}"
        if self.analysis_box.isChecked() and camera.settings.get("record", True):
            state += f"; riders {self._riders_progress(camera)}"
        camera.item.setText(f"{camera.settings.get('name', camera.id)}: {state}")

    def _riders_progress(self, camera: Camera) -> str:
        """How far the camera's analyser has got (FR-009)."""
        progress = camera.activity.progress or {}
        if progress.get("state") == "failed":
            return str(progress.get("detail") or "cannot be found")
        done = progress.get("done_ms")
        if done is None:
            return "not found yet"
        behind = int(camera.index.ms[-1]) - int(done) if len(camera.index) else 0
        return "up to date" if behind <= 3000 else f"{behind // 1000} s behind"

    def step(self, frames: int) -> None:
        camera, place = self._camera(), self._place()
        if camera is not None and place is not None:
            self._leave_live()
            self._go(camera.index.step(place, frames))

    def step_ms(self, ms: int) -> None:
        camera, place = self._camera(), self._place()
        if camera is not None and place is not None:
            self._leave_live()
            self._go(camera.index.step_ms(place, ms))

    def _place(self) -> int | None:
        """The frame stepped from: the one shown, or else, for a camera that did not
        film the moment shown, its frame nearest that moment."""
        camera = self._camera()
        if self.place is not None or camera is None or self.moment is None:
            return self.place
        return camera.index.nearest(self.moment - self._offset())

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
        kept = {
            c.id: (c.index.generation, self._frame_shown(c))
            for c in self.cameras.values()
        }
        grown = [other.index.refresh() for other in self.cameras.values()]
        for other in self.cameras.values():
            generation, frame = kept[other.id]
            if other.index.generation != generation and frame is not None:
                other.shown, other.wanted = other.index.find(frame), None  # sorted anew
                if other.id == self.current:
                    self.place, force = other.shown, True
        camera = self._camera()
        if camera is None:
            self.timeline.set_recording(np.empty(0, np.int64), [])
            return
        if not any(grown) and not force:
            return
        offset = self._offset()
        gaps = [(g.start_ms + offset, g.end_ms + offset) for g in camera.index.gaps]
        self.timeline.set_recording(camera.index.ms, gaps, offset)
        nothing_yet = self.place is None and self.moment is None
        if len(camera.index) and (self.live or nothing_yet):
            self._go(len(camera.index) - 1)
        elif self.place is not None:
            self._go(self.place)  # the frame shown, maybe at a new place, asked again

    def _frame_shown(self, camera: Camera) -> Frame | None:
        return None if camera.shown is None else camera.index.frame(camera.shown)

    def _go(self, place: int) -> None:
        camera = self._camera()
        if camera is None:
            return
        self.place = place
        frame = camera.index.frame(place)
        moment = self.moment = frame.ms + self._offset()
        self.timeline.set_position(moment)
        clock = scale_time(self._line_ms(moment)).split(" ")[1]
        self.time_label.setText(f"{clock} LIVE" if self.live else clock)
        source = int(self.session.get("source_offset_ms", 0))
        self.source_label.setText(f"source {source:+d} ms")
        self._follow_lists(moment)
        for other in self.cameras.values():
            self._show_at(other, place if other is camera else None, moment)
        self._show_marks()

    def _show_at(self, camera: Camera, place: int | None, moment: int) -> None:
        """The camera's frame at ``place``, or else its frame nearest ``moment`` --
        none when the nearest is more than NEAR_MS away: a camera that did not film
        that moment says so instead of showing another."""
        if place is None:
            target = moment - int(camera.settings.get("offset_ms", 0))
            place = camera.index.nearest(target)
            if (
                place is not None
                and abs(camera.index.frame(place).ms - target) > NEAR_MS
            ):
                place = None
        camera.shown = place
        if place is None:
            camera.wanted = None
            if len(camera.index):
                camera.view.show_text("No frame at this moment")
            return
        if (camera.id, place) == camera.wanted:
            return
        camera.wanted = (camera.id, place)
        frame = camera.index.frame(place)
        camera.view.show_waiting()  # no crossing timed on the frame before
        camera.worker.request(frame.path, frame.pts, camera.wanted)

    def _decoded(self, tag: tuple[str, int], image: QImage) -> None:
        """A frame decoded, handed over in this window's thread: a lambda would run
        in the decoder's, where no widget may be touched."""
        camera = self.cameras.get(tag[0])
        if camera is None or tag != camera.wanted:
            return  # an answer to a request since replaced, or a camera removed
        if image.isNull():
            camera.view.show_text("This frame cannot be shown")
        else:
            camera.view.show_image(image)

    # -- cameras in step -------------------------------------------------------

    def mark_event(self) -> None:
        """The shared event at the frame shown. The first camera it is marked on
        sets its moment; each camera marked after takes the offset that shows the
        event at that moment. Once every camera is aligned, or after EVENT_S, the
        next mark is a new event."""
        camera = self._camera()
        if camera is None or self.place is None:
            self._say("Show the event on a camera first")
            return
        name = camera.settings.get("name", camera.id)
        frame = camera.index.frame(self.place)
        event, now = self.shared_event, time.monotonic()
        if event is None or event.camera == camera.id or now - event.since > EVENT_S:
            self.shared_event = SharedEvent(camera.id, frame.ms + self._offset(), now)
            self._say(f"Event marked on {name}: now show it on the other cameras")
            return
        offset = event.moment - frame.ms
        camera.settings["offset_ms"] = offset
        self._save_session()
        event.aligned.add(camera.id)
        if event.aligned >= set(self.cameras) - {event.camera}:
            self.shared_event = None  # every camera aligned on it
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
            self._stop_analyzer(camera)
        super().closeEvent(event)


def _same_file(chosen: object, path: str) -> bool:
    """The session's file ``chosen`` is the one at ``path``; none chosen is none."""
    return bool(chosen) and app_path(str(chosen)).resolve() == app_path(path).resolve()


def start_analyzer(camera_id: str, parent: QWidget) -> QProcess:
    """A camera's analyser, a child of the window: it ends when its input closes,
    and it may die with the window; the recordings do not."""
    process = QProcess(parent)
    program, *arguments = command(camera_id, "--analyzer")
    process.setProgram(program)
    process.setArguments(arguments)
    process.setWorkingDirectory(str(paths.base_dir()))
    environment = QProcessEnvironment.systemEnvironment()
    if not getattr(sys, "frozen", False):
        environment.insert("PYTHONPATH", package_root())
    process.setProcessEnvironment(environment)
    process.setStandardOutputFile(QProcess.nullDevice())
    process.setStandardErrorFile(QProcess.nullDevice())  # unread, it would pile up
    process.start()
    return process


def usb_cameras() -> list[str]:
    """The names of the cameras on this computer, as the system lists them."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
    except ImportError:  # pragma: no cover - a Qt without multimedia
        return []
    return [device.description() for device in QMediaDevices.videoInputs()]
