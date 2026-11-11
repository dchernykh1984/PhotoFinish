"""The PhotoFinish main window: layout and wiring. What is not drawing lives in the
Qt-free modules (session, video_index, recorder) and the widgets."""

from __future__ import annotations

import html
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import (
    QDateTime,
    QObject,
    QProcess,
    QProcessEnvironment,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QImage, QKeySequence, QShortcut, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from app import analysis, cameras, paths, phone_status, playback, session, shared_event
from app.analysis import models
from app.analysis.activity import Activity, how_far
from app.analysis.suggestions import Gathered, Suggestions, gathered, remaining
from app.input_follow import InputFollow
from app.interpolation import (
    Line,
    Point,
    between,
    camera_line,
    crossing,
    own_line,
    points,
)
from app.lines import (
    clock_of,
    parse_line,
    parse_time,
    scale_time,
    source_offset,
    to_epoch,
    to_line_scale,
)
from app.output_list import Change, JournalError, OutputLine, OutputList
from app.paths import app_path
from app.recorder import folder_of, free_ids
from app.recorder.launcher import (
    Watchdog,
    child_environment,
    command,
    describe,
    heartbeat,
    recording,
)
from app.video_index import FileIndex, Frame, VideoIndex
from app.widgets.camera_dialog import CameraDialog
from app.widgets.camera_view import CameraView
from app.widgets.decode_worker import DecodeWorker
from app.widgets.lists import LinesView, input_rows, output_rows
from app.widgets.number_field import NumberField
from app.widgets.timeline import Timeline

POLL_MS = 500
PLAY_MS = 15  # how often playing looks for the next frame: oftener than any camera's
FOLLOW_S = 0.25  # how often the lists follow a video playing: not at every frame
NEAR_MS = 1000  # another camera's frame further from the moment than this: none
STOP_MS = 3000  # an analyser stopped is killed if it has not ended by then
OUTSIDE = "The output file was changed outside PhotoFinish: kept beside it"
# The corner's word on recording (FR-019): large, white on green or on red.
BANNER = (
    "QLabel {{ background: {}; color: white; font-size: 24px; font-weight: bold;"
    " padding: 6px; border-radius: 4px; }}"
)
GREEN, RED = "#2e7d32", "#c62828"
LEVELS = {phone_status.WARN: "#b26a00", phone_status.BAD: RED}  # a phone's readings


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
    wanted: tuple[str, Frame] | None = None  # the frame last asked for
    pending: bool = False  # that frame asked for and not decoded yet
    analyzer: Any = None  # its analyser process, while finding riders is on
    analyzer_started: float = -math.inf  # monotonic
    stopping: Any = None  # the analyser stopped, while it ends its segment
    info: dict[str, Any] | None = None  # its recorder's last heartbeat

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
        self.playing = False
        self.play_from: int | None = None  # the moment Play started from, for Stop
        self._play_start = (0.0, 0)  # the clock and the moment playing started at
        self._followed = -math.inf  # when the lists last followed the video
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._play_tick)
        self.play_button = QPushButton("Pause")  # live, the video plays on
        self.shared_event: shared_event.SharedEvent | None = None

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
        self.recording_banner = QLabel()  # whether the cameras record now (FR-019)
        self.recording_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recording_banner.setTextFormat(Qt.TextFormat.RichText)
        self.recording_banner.setWordWrap(True)
        self.recording_banner.hide()  # until a camera records
        self.phones = QLabel()  # what may stop each phone's stream (specs/005)
        self.phones.setTextFormat(Qt.TextFormat.RichText)
        self.phones.setWordWrap(True)
        self.phones.setStyleSheet("QLabel { font-size: 13px; }")
        self.phones.hide()  # until a phone says how it is
        self.camera_list = QListWidget()
        self.camera_list.setWordWrap(True)
        self.camera_list.currentRowChanged.connect(self._choose_camera)
        self.one_camera = QPushButton("One camera")  # the chosen one alone (004)
        self.one_camera.setCheckable(True)
        self.one_camera.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.one_camera.setToolTip(
            "The chosen camera alone, large. Ctrl+1 to Ctrl+9: that camera alone; "
            "Ctrl+0: all side by side; Ctrl+Up, Ctrl+Down: the previous, the next"
        )
        self.one_camera.toggled.connect(self._one_camera_toggled)
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
        self.crossings_box = QCheckBox("Numbers and crossings")  # with it on (006)
        self.crossings_box.setToolTip(
            "The model chosen finds the riders, suggests their crossings of the finish "
            "line and reads their numbers; off, riders are found by motion alone"
        )
        self.crossings_box.setChecked(analysis.settings(self.session)["crossings"])
        self.crossings_box.toggled.connect(self._crossings_on)
        self.model_box = _StillCombo()
        self.model_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the keys move video
        self.model_box.setToolTip(
            "What finds riders: motion in the zone, or a detection model, downloaded "
            "once when first chosen"
        )
        self.model_box.activated.connect(self._model_chosen)
        self._job: models.Download | None = None  # the download in progress
        # Its detector turns Numbers and crossings on as it comes: chosen in the list,
        # and the switch left alone since.
        self._job_turns_on = False
        self._fetch = _Fetch()
        self._fetch.progress.connect(self._fetch_progress)
        self._fetch.done.connect(self._fetched)
        self._numbers_job: models.Download | None = None  # the number reader's (006)
        self._numbers_fetch = _Fetch()
        self._numbers_fetch.done.connect(self._numbers_fetched)
        self._show_model()
        self._show_switches()
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
        models.clear_parts()  # no download of this window's is running yet
        self._ensure_model()  # before the first poll starts any analyser
        self._ensure_numbers()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_MS)
        self.poll()
        self._show_suggestions()

    # -- layout ----------------------------------------------------------------

    def _layout(self) -> QSplitter:
        moves = []
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
            button.clicked.connect(slot)
            moves.append(button)
        self.play_button.setToolTip(
            "Play the video at its own speed from the frame shown, or hold the frame"
        )
        self.play_button.clicked.connect(self.play_or_pause)
        stop = QPushButton("Stop")
        stop.setToolTip("Stop playing and go back to the frame Play started from")
        stop.clicked.connect(self.stop)
        transport = QHBoxLayout()
        for button in (*moves[:3], self.play_button, stop, *moves[3:]):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            transport.addWidget(button)
        transport.addStretch()
        transport.addWidget(self.source_label)
        transport.addWidget(self.time_label)
        self.edit_line = QPushButton("Edit finish line")  # its edit mode (006)
        self.edit_line.setCheckable(True)
        self.edit_line.setToolTip(
            "Click the line's two ends on a picture: the line of every camera that "
            "follows the common one -- or, with 'This camera only', that camera's own"
        )
        self.edit_line.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.edit_line.toggled.connect(self._edit_line)
        self.this_camera_only = QCheckBox("This camera only")
        self.this_camera_only.setToolTip(
            "The line drawn is this camera's own, kept when the common one moves"
        )
        self.this_camera_only.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.this_camera_only.setEnabled(False)  # in the edit mode only
        event_button = QPushButton("Mark event")
        event_button.setToolTip(
            "Mark one moment every camera shows -- a flash, a hand wave -- on each "
            "camera in turn: they are aligned on it"
        )
        event_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        event_button.clicked.connect(self.mark_event)
        timing = QHBoxLayout()
        timing.addWidget(self.edit_line)
        timing.addWidget(self.this_camera_only)
        timing.addWidget(event_button)
        timing.addWidget(QLabel("Number"))
        timing.addWidget(self.number, stretch=1)
        timing.addWidget(self.finish)
        timing.addWidget(self.output_button)
        zone_button = QPushButton("Zone")
        zone_button.setToolTip("Click two corners of where riders pass the line")
        zone_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        zone_button.clicked.connect(self.draw_zone)
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
        finding.addWidget(self.crossings_box)
        finding.addWidget(zone_button)
        finding.addWidget(self.model_box)
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
        buttons.addWidget(self.one_camera)
        cameras = QVBoxLayout()
        cameras.addWidget(self.recording_banner)
        cameras.addWidget(self.phones)
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
        corrections = QGridLayout()  # two rows: in one they need more than 320 px
        for place, (label, slot) in enumerate(
            (
                ("Time from frame", self.time_from_frame),
                ("Type time...", self.type_time),
                ("Number...", self.change_number),
                ("Remove...", self.remove_line),
            )
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            corrections.addWidget(button, place // 2, place % 2)
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
        # Never narrower than its rows need: a set minimum below that cuts labels.
        right.setMinimumWidth(max(320, right.minimumSizeHint().width()))

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
            ("Ctrl+0", lambda: self.show_alone(None)),
            ("Ctrl+Up", lambda: self.next_camera(-1)),
            ("Ctrl+Down", lambda: self.next_camera(1)),
            *((f"Ctrl+{n}", partial(self.show_alone, n - 1)) for n in range(1, 10)),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(slot)

    def show_alone(self, row: int | None) -> None:
        """Camera ``row`` of the list alone, large; None: every camera side by side.
        A row with no camera changes nothing."""
        if row is None:
            self.one_camera.setChecked(False)
        elif row < self.camera_list.count():
            self.camera_list.setCurrentRow(row)
            self.one_camera.setChecked(True)

    def next_camera(self, step: int) -> None:
        """The next camera of the list, or the previous, at the moment shown."""
        count = self.camera_list.count()
        if count:
            row = self.camera_list.currentRow()
            if (
                row < 0
            ):  # none chosen: down from before the first, up from past the last
                row = -1 if step > 0 else count
            self.camera_list.setCurrentRow((row + step) % count)

    def _one_camera_toggled(self) -> None:
        self._arrange()
        self._refresh(force=True)  # the cameras shown again ask for their frames

    # -- cameras ---------------------------------------------------------------

    def add_camera(self) -> None:
        """A camera, or a phone's camera for each of its lenses ticked (004)."""
        cameras_now = self.session["cameras"]
        first, *spare = free_ids(self.cameras, len(cameras.LENSES))
        dialog = CameraDialog(self, first, usb_cameras(), cameras_now, spare)
        if dialog.exec() != CameraDialog.DialogCode.Accepted:
            return
        row = self.camera_list.count()
        added = dialog.cameras()
        self.session["cameras"].extend(added)
        self._save_session()  # before their recorders start: they read the session
        for camera in added:
            self._add(camera)
        self.camera_list.setCurrentRow(row)

    def remove_camera(self) -> None:
        camera = self._camera()
        if camera is None:
            return
        name = self._name(camera.id)
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
        self._show_suggestions()  # its suggestions gone with it

    def _add(self, settings: dict[str, Any]) -> None:
        camera_id = str(settings["id"])
        item = QListWidgetItem(str(settings.get("name", camera_id)))
        item.setData(Qt.ItemDataRole.UserRole, camera_id)
        self.camera_list.addItem(item)
        view, worker = CameraView(), DecodeWorker()
        recorded = settings.get("record", True) or settings.get("connection") != "file"
        given = settings.get("settings")  # a session edited by hand may lack it
        path = given.get("path") if isinstance(given, dict) else None
        index = (
            FileIndex(app_path(str(path)))
            if not recorded and path
            else VideoIndex(folder_of(camera_id))
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
        """The cameras' views side by side, as square a grid as they make; in
        one-camera mode the chosen camera's alone, over the whole area."""
        views = [camera.view for camera in self.cameras.values()]
        alone = self._hidden_others()
        shown = [self.view] if alone else views or [self.placeholder]
        self.placeholder.setVisible(not self.cameras)
        for view in views:
            if view not in shown:
                self.grid.removeWidget(view)
                view.setVisible(False)
        columns = math.ceil(math.sqrt(len(shown)))
        for n, view in enumerate(shown):
            self.grid.addWidget(view, n // columns, n % columns)
            view.setVisible(True)  # in the grid first: shown alone, it is a window

    def _hidden_others(self) -> bool:
        """One-camera mode, with a camera chosen: the others are hidden."""
        return self.one_camera.isChecked() and self._camera() is not None

    @property
    def view(self) -> CameraView:
        """The view of the camera chosen, or the one that says to add a camera."""
        camera = self._camera()
        return self.placeholder if camera is None else camera.view

    def _choose_camera(self, row: int) -> None:
        """Another camera to step through; the moment shown stays. A line or zone
        half drawn is given up: its ends must come from one camera's picture."""
        if self.drawing is not None:
            # A line's edit mode starts over on the camera chosen; a zone is given up.
            line = self.edit_line.isChecked()
            if self.drawing or not line:  # an end clicked on the other: said
                self._say(
                    "The line starts over: both ends on one camera's picture"
                    if line
                    else "Drawing stopped: click both ends on one camera's picture"
                )
            self.drawing = [] if line else None
        item = self.camera_list.item(row) if row >= 0 else None
        self.current = (
            None if item is None else str(item.data(Qt.ItemDataRole.UserRole))
        )
        camera = self._camera()
        for other in self.cameras.values():
            other.view.chosen = other is camera
            other.view.update()
        if self.one_camera.isChecked():
            self._arrange()  # the camera chosen is the one shown
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
        if not self._frame_on_screen():
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
        self._show_suggestions()  # their times, on the new scale

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
        said = False  # a word said once: a refused copy is said at the next poll
        try:
            if self.follow is not None and self.follow.poll():
                self._show_lists()
            if self.output is not None:
                self.output.check_outside()
                if self.output.outside_kept:  # by this check, or by a change before
                    self.output.outside_kept = False
                    self._say(OUTSIDE)
                    said = True
                    self._show_lists()
        except JournalError as error:  # lines taken, or an outside version kept
            self._say(f"Written; the journal cannot take it: {error}")
            said = True
            self._show_lists()
        except OSError as error:
            self._say(f"The files cannot be followed: {error}")
        finally:  # said last: a failing poll says its own again at the next one
            if self.output is not None and not said:
                refused, self.output.copy_refused = self.output.copy_refused, None
                if refused is not None:
                    self._say(
                        f"Written; its copy in temp/ cannot be written: {refused}"
                    )

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

    def _edit_line(self, on: bool) -> None:
        """The finish line's edit mode (006): two clicks on a picture set the common
        line, or with "This camera only" that camera's own; the mode stays on for
        the next until turned off. Out of it, clicks belong to the caliper."""
        self.this_camera_only.setEnabled(on)
        if not on:  # the next edit moves the common line, unless ticked again
            self.this_camera_only.setChecked(False)
        if on and self._camera() is None:
            self._say("Add a camera first")
            self.edit_line.setChecked(False)
            return
        if on:
            self._start_drawing(
                "finish_line", "Click one end of the finish line, then the other"
            )
        elif self.drawn == "finish_line" and self.drawing is not None:
            self.drawing = None
            self._show_marks()

    def _line(self, camera: Camera) -> Line:
        """The finish line the camera times on: its own, or the common one."""
        return camera_line(camera.settings, self.session.get("finish_line"))

    def draw_zone(self) -> None:
        """The next two clicks on the picture are corners of the zone where riders
        pass the line: motion elsewhere is not looked at."""
        self.edit_line.setChecked(False)  # one thing drawn at a time
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
        point of the finish line being drawn -- in the edit mode, the first end of
        one on that camera -- or of the caliper."""
        if camera_id is not None and camera_id != self.current:
            zone = self.drawing is not None and not self.edit_line.isChecked()
            self.camera_list.setCurrentRow(list(self.cameras).index(camera_id))
            if zone:
                return  # the zone half drawn was given up: this click chose the camera
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
        ends = [list(end) for end in drawing]
        if zone:
            camera.settings["zone"] = ends
            changed, said = [camera], "The zone is drawn"
        else:
            changed, said = self._set_line(camera, ends)
        self._save_session()
        self._restart_analyzers(changed)  # the new line or zone from here on
        self.drawing = None if zone else []  # the line's edit mode stays on
        self._say(said)

    def _set_line(
        self, camera: Camera, ends: list[list[float]]
    ) -> tuple[list[Camera], str]:
        """The line drawn on ``camera``: its own with "This camera only", else the
        common line, which the camera follows again; the cameras it moves, said."""
        if self.this_camera_only.isChecked():
            camera.settings |= {"finish_line": ends, "own_line": True}
            return [camera], "This camera's own finish line is drawn"
        self.session["finish_line"] = ends
        camera.settings["own_line"] = False
        moved = [c for c in self.cameras.values() if not own_line(c.settings)]
        return moved, "The finish line is drawn for every camera that follows it"

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
        fraction = crossing(self._line(camera), a, b)
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
            [f.ref() for f in frames],
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
            [f.ref() for f in frames],
            None,
            self._offsets(),
        )
        self._offer(self._line_ms(ms), change)

    def _frame_on_screen(self) -> bool:
        """False, said, while the frame stepped to is still on its way: the picture
        on screen is the one before, and timing on it would time another frame."""
        if self.playing:
            self._say("Pause the video first: the frame shown is moving")
            return False
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
        chosen = self.output_view.chosen()  # the line itself: it may move meanwhile
        target = (
            None if chosen is None or not self.output else self.output.lines[chosen]
        )
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
        at = None if target is None else self._index_of(target)  # said when gone
        if at is not None:
            self._correct(lambda output: output.set_time(at, ms, change))

    def _show_marks(self) -> None:
        """Each view: its camera's finish line, the points clicked on its frame."""
        for camera in self.cameras.values():
            shown = None if camera.shown is None else camera.index.frame(camera.shown)
            marks = [
                p for c, frame, p in self.caliper if c == camera.id and frame == shown
            ]
            if camera.id == self.current:
                marks += self.drawing or []
            common = self.session.get("finish_line")
            on = self.analysis_box.isChecked()
            camera.view.show_marks(
                self._line(camera),
                marks,
                analysis.zone(camera.settings, common) if on else None,
            )

    # -- finding riders (experimental) -------------------------------------------

    def _own_model(self) -> str | None:
        """A model file of the referee's own, None when none is chosen."""
        path, _ = QFileDialog.getOpenFileName(
            self, "A YOLOX detection model of your own", "", "ONNX model (*.onnx)"
        )
        return path or None

    def _model_chosen(self, index: int) -> None:
        """A preset ready is chosen at once, one missing is downloaded first; the
        last item opens a file of the referee's own. A choice made stops the download
        in progress; a file dialog closed without one leaves it going."""
        chosen = self.model_box.itemData(index)
        if chosen == _OWN_FILE:
            chosen = self._own_model()
            if chosen is None:
                self._show_model()  # the model, and its download, as they were
                return
        if self._job is not None:
            if chosen == self._job.model.file:
                self._job_turns_on = (
                    True  # on its way already: chosen for its crossings
                )
                return
            self._job.cancel()
            self._job = None
            self._show_model()  # the stopped one's progress off its line
        model = models.preset(chosen)
        if model is not None and not models.ready(model):
            self._download(model)
            self._job_turns_on = True  # chosen for its crossings, as one ready is
        elif chosen != analysis.settings(self.session)["model"]:
            self._set_model(chosen)
        elif chosen and not analysis.settings(self.session)["crossings"]:
            self.crossings_box.setChecked(True)  # chosen again: for its crossings
        else:
            self._show_model()  # the one in use again: nothing restarted, list redone

    def _ensure_model(self) -> None:
        """The preset in use downloaded when it is missing -- an event folder copied
        without models/, a new copy of the program -- once finding riders is on:
        never for a feature nobody turned on, nor on every start of an offline race.
        """
        model = models.preset(analysis.model_in_use(self.session))
        on = self.analysis_box.isChecked()
        if on and model is not None and self._job is None and self._model_missing():
            self._download(model)

    def _model_missing(self) -> bool:
        """The preset in use is not on the disk: on its way, or failed to come."""
        model = models.preset(analysis.model_in_use(self.session))
        return model is not None and not models.ready(model)

    def _download(self, model: models.Model) -> None:
        """The model fetched in the background; choosing anything else in the list
        stops it."""
        self._say(f"Downloading {model.label}...")
        self.model_box.setCurrentIndex(self.model_box.findData(model.file))  # shown
        self._job = self._fetch.start(model)
        self._job_turns_on = False

    def _fetch_progress(self, job: models.Download, done: int) -> None:
        """How far the download is, in the model list itself: the status line keeps
        whatever warning it shows."""
        if job is self._job:
            model = job.model
            self.model_box.setItemText(
                self.model_box.findData(model.file),  # its own line, chosen or not
                f"{model.title}: {math.ceil(done / 1_000_000)} of {model.megabytes} MB",
            )

    def _fetched(self, job: models.Download, error: str) -> None:
        if job is not self._job:
            return  # a download since stopped, or the window gone
        self._job, model = None, job.model
        if error:
            self._say(error)
            self._show_model()
            return
        self._say(f"{model.title} downloaded")
        self._set_model(model.file, turn_on=self._job_turns_on)

    def _set_model(self, path: str, turn_on: bool = True) -> None:
        """The model chosen; a detector chosen turns numbers and crossings on, what
        it is chosen for -- off, it would run motion alone without a word. One
        downloaded leaves the switch as the referee left it meanwhile."""
        chosen = {**analysis.settings(self.session), "model": path}
        chosen["crossings"] = chosen["crossings"] or (turn_on and bool(path))
        self.session["analysis"] = chosen
        self._save_session()
        self.crossings_box.blockSignals(True)  # its analysers restarted below
        self.crossings_box.setChecked(chosen["crossings"])
        self.crossings_box.blockSignals(False)
        self._ensure_numbers()  # the detector's crossings read with numbers
        self._show_model()
        self._show_suggestions()
        self._restart_analyzers()  # the model chosen from here on

    def _show_model(self) -> None:
        """The presets, a file of the referee's own when one is chosen, and the model
        in use selected."""
        chosen = analysis.settings(self.session)["model"]
        self.model_box.clear()
        self.model_box.addItem("Motion only", "")
        for model in models.MODELS:
            self.model_box.addItem(model.label, model.file)
        if chosen and models.preset(chosen) is None:
            self.model_box.addItem(f"Model: {Path(chosen).name}", chosen)
        self.model_box.addItem("Model file...", _OWN_FILE)
        self.model_box.setCurrentIndex(self.model_box.findData(chosen))

    def _crossings_on(self, on: bool) -> None:
        """Numbers and crossings looked for with the model chosen, or not: every
        analyser started again on what it now runs -- none with no model chosen,
        motion alone either way."""
        self.session["analysis"] = {**analysis.settings(self.session), "crossings": on}
        self._job_turns_on = False  # the referee's word since a detector was chosen
        self._save_session()
        self._show_switches()
        self._ensure_model()
        self._ensure_numbers()
        if analysis.settings(self.session)["model"]:
            self._restart_analyzers()
        self._show_suggestions()

    def _ensure_numbers(self, said: bool = False) -> None:
        """The number reader's two models downloaded, one after the other, once
        riders are found with numbers and crossings (006, FR-002): never for a
        feature nobody turned on. The download is said once, ``said`` already for
        the second."""
        chosen = analysis.settings(self.session)
        missing = [m for m in models.NUMBER_MODELS if not models.ready(m)]
        wanted = chosen["on"] and chosen["crossings"] and chosen["model"]
        if not (wanted and missing):  # numbers are read only on a detector's crossings
            return
        if self._numbers_job is None:
            if not said:
                megabytes = sum(model.megabytes for model in missing)
                self._say(f"Downloading the number reader ({megabytes} MB)...")
            self._numbers_job = self._numbers_fetch.start(missing[0])

    def _numbers_fetched(self, job: models.Download, error: str) -> None:
        if job is not self._numbers_job:
            return  # the window going: nothing to start
        self._numbers_job = None
        if error:
            self._say(f"{error}: crossings are suggested without numbers")
            return
        if not all(models.ready(m) for m in models.NUMBER_MODELS):
            self._ensure_numbers(said=True)  # the next of them
            return
        self._say("The number reader is ready")
        if analysis.model_in_use(self.session):  # crossings still looked for
            self._restart_analyzers()  # numbers read from here on

    def _show_switches(self) -> None:
        """Numbers and crossings with finding riders on. The model stays open to
        choose, and to download before the race, whatever the switches say."""
        self.crossings_box.setEnabled(self.analysis_box.isChecked())

    def _analysis_on(self, on: bool) -> None:
        self.session["analysis"] = {**analysis.settings(self.session), "on": on}
        self._save_session()
        self._show_switches()
        self._ensure_model()
        self._ensure_numbers()
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
        if self._model_missing():
            return  # started once it is there, never on a file that is not
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

    def _restart_analyzers(self, cameras: Iterable[Camera] | None = None) -> None:
        """The analysers, of every camera or of ``cameras``, started again on what
        they now run, while riders are found."""
        if not self.analysis_box.isChecked():
            return
        for camera in self.cameras.values() if cameras is None else cameras:
            self._stop_analyzer(camera)
            self._analyze(camera)

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
        """The crossing suggested -- by one camera or several, at the median
        camera's moment -- with the number typed, else the one read, through the
        output's usual path; the journal names that camera and its model."""
        suggested = self._suggestion()
        if suggested is None:
            return
        number = self.number.text().strip() or suggested.number
        if self.output is None or not number:
            self._say("Type the rider's number first; the output file must be chosen")
            return
        _, camera_id, found = suggested.kept
        camera = self.cameras[camera_id]
        offsets = self._offsets(camera)
        # On the camera's offset as it is now: aligned since the list was made,
        # the time written follows -- as the video picked does.
        line_ms = self._line_ms(int(found["ms"]) + offsets["camera_ms"])
        change = Change(
            "interpolated",
            camera.id,
            found.get("frames", []),
            found.get("fraction"),
            offsets,
            str(found.get("model", "")),
        )
        action = self._action()
        if not self._correct(
            lambda output: output.add(number, line_ms, action, change)
        ):
            return  # not written: the suggestion stays offered, the number typed
        self.number.clear()
        self._decide(suggested, "accepted")

    def dismiss_suggestion(self) -> None:
        chosen = self._suggestion()
        if chosen is not None:
            self._decide(chosen, "dismissed")

    def _decide(self, suggested: Gathered, how: str) -> None:
        """A crossing decided leaves the list, with every camera's suggestion of it;
        a decision the disk refuses is said: offered again after a restart, it
        would be accepted twice."""
        refused, why = [], ""
        for _, camera_id, found in suggested.seen:
            camera = self.cameras.get(camera_id)
            if camera is None:
                continue
            try:
                camera.suggestions.decide(str(found["id"]), how)
            except OSError as error:
                refused.append(self._name(camera_id))
                why = str(error)
        if refused:  # once, naming each camera whose decision it is
            names = ", ".join(refused)
            self._say(
                f"Done; the decision cannot be kept for a restart ({names}): {why}"
            )
        self._show_suggestions()

    def _suggestion(self) -> Gathered | None:
        item = self.suggestion_list.currentItem()
        suggested = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(suggested, Gathered) or suggested.kept[1] not in self.cameras:
            self._say("Choose a suggested crossing first")
            return None
        return suggested

    def _suggestion_picked(self, item: QListWidgetItem) -> None:
        """The video at the suggested moment, on the camera at the median."""
        suggested = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(suggested, Gathered) or suggested.kept[1] not in self.cameras:
            return
        _, camera_id, found = suggested.kept
        self.camera_list.setCurrentRow(list(self.cameras).index(camera_id))
        self.seek_ms(int(found["ms"]) + self._offset())

    def _show_suggestions(self) -> None:
        """The crossings suggested and not decided, in time order; the one chosen
        stays chosen."""
        item = self.suggestion_list.currentItem()
        data = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        chosen = (
            {str(s[2].get("id")) for s in data.seen}
            if isinstance(data, Gathered)
            else set()
        )
        self.suggestion_list.clear()
        settings = analysis.settings(self.session)
        if not settings["on"]:
            return
        if not settings["model"]:  # what to do first: choosing one turns them on
            self._hint(
                "Suggestions need a detection model: choose one in the model list"
            )
            return
        if not settings["crossings"]:
            self._hint(
                "Numbers and crossings are off: riders are found by motion alone"
            )
            return
        found = [  # the decided too: a late camera's suggestion may join one
            (int(s["ms"]) + int(c.settings.get("offset_ms", 0)), c.id, s)
            for c in self.cameras.values()
            for s in c.suggestions.found
        ]
        listed: list[tuple[Gathered, str]] = []
        for whole in gathered(found):  # every camera's suggestion of one, once
            suggested, how = remaining(whole, self._decision)
            if suggested is not None:
                listed.append((suggested, how))
        listed.sort(key=lambda left: left[0].moment)  # in time order, as shown
        for suggested, how in listed:
            said = f"  (one {how} with it)" if how else ""
            item = QListWidgetItem(self._suggestion_text(suggested) + said)
            item.setToolTip(
                "\n".join(
                    f"{self._name(camera_id)}: {clock_of(self._line_ms(moment))} "
                    f"by {suggestion.get('model')}"
                    for moment, camera_id, suggestion in suggested.seen
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, suggested)
            self.suggestion_list.addItem(item)
            if chosen & {str(s[2].get("id")) for s in suggested.seen}:
                self.suggestion_list.setCurrentItem(item)

    def _hint(self, said: str) -> None:
        """A line of the suggestion list that is no suggestion."""
        hint = QListWidgetItem(said)
        hint.setFlags(Qt.ItemFlag.NoItemFlags)
        self.suggestion_list.addItem(hint)

    def _decision(self, camera_id: str, found: dict[str, Any]) -> str | None:
        """How a camera's suggestion was decided, None while it is not."""
        camera = self.cameras.get(camera_id)
        return (
            None
            if camera is None
            else camera.suggestions.done.get(str(found.get("id")))
        )

    def _suggestion_text(self, suggested: Gathered) -> str:
        """A crossing in the list: its moment, the cameras that saw it, the number
        read."""
        names = ", ".join(self._name(camera_id) for _, camera_id, _ in suggested.seen)
        number = f"  no. {suggested.number}" if suggested.number else ""
        return f"{clock_of(self._line_ms(suggested.moment))}  {names}{number}"

    def _name(self, camera_id: str) -> str:
        camera = self.cameras.get(camera_id)
        return (
            camera_id if camera is None else str(camera.settings.get("name", camera_id))
        )

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
        frames = [frame.ref()]
        return line_ms, Change("frame", camera.id, frames, None, self._offsets())

    def _open_output(self, again: bool = False) -> None:
        """The output chosen opened, and the input followed into it. One that cannot
        be opened -- held a moment by another program -- is tried at every poll."""
        chosen = str(self.session.get("output") or "")
        self.output_button.setText(f"Output: {chosen}" if chosen else "Output file...")
        self.output = None
        if chosen:
            try:
                self.output = OutputList(app_path(chosen))
            except OSError as error:
                if again:
                    return  # said when it was first tried
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
            camera.info = self._label(camera)
        self._show_recording()
        self._show_phones()
        if suggested:
            self._show_suggestions()
        if self.output is None and self.session.get("output"):
            self._open_output(again=True)
        self._follow_files()
        self._refresh()
        current = self._camera()
        stretches = current.activity.stretches if current and finding else []
        offset = self._offset()
        self.timeline.set_stretches([(a + offset, b + offset) for a, b in stretches])

    def _label(self, camera: Camera) -> dict[str, Any] | None:
        """The camera's line in the list: its name and how its recorder is, as the
        heartbeat it returns says."""
        watchdog = camera.watchdog
        info = (watchdog.poll() if watchdog.wanted else None) or heartbeat(camera.id)
        if watchdog.wanted and watchdog.error:
            state = f"the recorder cannot be started: {watchdog.error}"
        elif info is not None:
            state = describe(info)
        else:
            state = "starting" if watchdog.wanted else "not recording"
        if camera.index.unreadable:
            state += f"; segments that cannot be read: {len(camera.index.unreadable)}"
        clash = cameras.port_clash(camera.settings, self.session["cameras"])
        if clash:
            state = f"{clash}; {state}"
        if self.analysis_box.isChecked() and camera.settings.get("record", True):
            if self._model_missing():
                in_use = analysis.model_in_use(self.session)
                coming = self._job is not None and self._job.model.file == in_use
                state += "; riders: the model is " + (
                    "downloading" if coming else "not here, choose it to download it"
                )
            else:
                state += f"; riders {self._riders_progress(camera)}"
            state += self._numbers_state(camera)
        camera.item.setText(f"{self._name(camera.id)}: {state}")
        return info

    def _numbers_state(self, camera: Camera) -> str:
        """What the camera line says while numbers go unread for want of the reader
        (006, FR-002): on its way, not here, or there and not loaded by the
        camera's analyser; nothing once it reads, or unwanted."""
        if not analysis.model_in_use(self.session):
            return ""
        if all(models.ready(m) for m in models.NUMBER_MODELS):
            unread = str((camera.activity.progress or {}).get("numbers") or "")
            return f"; numbers: {unread}" if unread else ""
        if self._numbers_job is not None:
            return "; numbers: the reader is downloading"
        return "; numbers: the reader is not here, turn Numbers and crossings on again"

    def _missing(self, camera: Camera) -> str:
        """A camera that does not record, as the corner names it: with the time of
        its last frame, on the timing source's scale as the time shown is."""
        name = self._name(camera.id)
        if not len(camera.index):
            return f"{name}: no video yet"
        last = int(camera.index.ms[-1]) + int(camera.settings.get("offset_ms", 0))
        clock = clock_of(self._line_ms(last), whole_seconds=True)
        return f"{name}: no video since {clock}"

    def _show_recording(self) -> None:
        """The corner's word (FR-019): nothing with no camera that records, green
        while every one records, red naming those that do not."""
        records = [c for c in self.cameras.values() if c.settings.get("record", True)]
        missing = [self._missing(c) for c in records if not recording(c.info)]
        banner = self.recording_banner
        banner.setVisible(bool(records))
        if missing:
            names = "<br>".join(html.escape(line) for line in missing)
            text = (
                "NOT RECORDING<br><span style='font-size: 14px; font-weight: normal'>"
                f"{names}</span>"
            )
        else:
            text = "RECORDING"
        style = BANNER.format(RED if missing else GREEN)
        banner.setText(text)
        if banner.styleSheet() != style:  # set again, it would be polished again
            banner.setStyleSheet(style)

    def _show_phones(self) -> None:
        """Under the banner, a line per phone with what may stop its stream, each
        reading amber or red as it worries (specs/005); a status no longer the
        phone's now greyed, with when it came: a recorder that stopped beating
        leaves its last status old too."""
        now = QDateTime.currentMSecsSinceEpoch()
        lines = []
        for camera in self.cameras.values():
            status = (camera.info or {}).get("phone")
            if not isinstance(status, dict) or not status:
                continue
            old = phone_status.stale(status, now)
            parts = [
                html.escape(text)
                if old or level not in LEVELS
                else f"<span style='color: {LEVELS[level]}'>{html.escape(text)}</span>"
                for text, level in phone_status.readings(status)
            ]
            if not parts:
                continue  # a status with no reading the phone could tell
            name = html.escape(self._name(camera.id))
            line = f"{name}: " + " &nbsp; ".join(parts)
            if old:
                heard = self._heard(camera, status)
                line = f"<span style='color: gray'>{line} &nbsp; {heard}</span>"
            lines.append(line)
        self.phones.setVisible(bool(lines))
        self.phones.setText("<br>".join(lines))

    def _heard(self, camera: Camera, status: dict[str, Any]) -> str:
        """When a phone's last status came, on the timing source's scale."""
        try:
            at = int(status["at_ms"]) + int(camera.settings.get("offset_ms", 0))
        except KeyError, TypeError, ValueError:
            return "last heard"
        return "at " + clock_of(self._line_ms(at), whole_seconds=True)

    def _riders_progress(self, camera: Camera) -> str:
        """How far the camera's analyser has got (FR-009)."""
        newest = int(camera.index.ms[-1]) if len(camera.index) else None
        return how_far(camera.activity.progress, newest)

    def step(self, frames: int) -> None:
        camera, place = self._camera(), self._place()
        if camera is not None and place is not None:
            self._moved()
            self._go(camera.index.step(place, frames))

    def step_ms(self, ms: int) -> None:
        camera, place = self._camera(), self._place()
        if camera is not None and place is not None:
            self._moved()
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
            self._moved()
            self._go(place)

    def go_live(self) -> None:
        self._halt(forget=True)
        self._set_live(True)
        camera = self._camera()
        if camera is not None and len(camera.index):
            self._go(len(camera.index) - 1)

    def _moved(self) -> None:
        """The referee moved the video: playing stops, Live is left, and Stop no
        longer goes back to where Play started."""
        self._halt(forget=True)
        self._set_live(False)

    def _set_live(self, live: bool) -> None:
        self.live = self.timeline.following = live
        self._show_play()

    # -- playing ---------------------------------------------------------------

    def play_or_pause(self) -> None:
        """Hold the video, live or playing; play it when it is held."""
        if self.live or self.playing:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        """The chosen camera's recording from the frame shown, at its own speed;
        the other cameras follow it, as they follow every move."""
        if self.moment is None:
            return  # nothing shown yet: no moment to play from
        self._set_live(False)
        self.playing, self.play_from = True, self.moment
        self._play_start = (time.monotonic(), self.moment)
        self.play_timer.start(PLAY_MS)
        self._show_play()

    def pause(self) -> None:
        """The frame shown held, and asked for again: one passed while playing may
        not have reached the screen, and timing waits for the one asked."""
        self._halt()
        self._set_live(False)
        if self.place is not None:
            self._go(self.place)

    def stop(self) -> None:
        """Playing stopped, back at the frame Play started from; after the referee
        moved the video, or Live caught it up, or with no frame to go back to,
        only held."""
        started = self.play_from
        self._halt()  # stopped, whatever follows
        if started is None:
            self.pause()
        else:
            self.seek_ms(started)

    def _halt(self, forget: bool = False) -> None:
        """Playing stops; ``forget`` also drops where Play started, so Stop no
        longer goes back there -- the one place that state is reset. A frame asked
        for while playing and still on its way was not dimmed: asked again,
        whatever moves the video next, so no crossing is timed on the frame
        before. One on screen already is the frame asked: left as it is."""
        if self.playing:
            for camera in self.cameras.values():
                if camera.pending:
                    camera.wanted, camera.pending = None, False
        self.playing = False
        self.play_timer.stop()
        if forget:
            self.play_from = None
        self._show_play()

    def _play_tick(self) -> None:
        """The frame due now, by the clock since Play, once the one on its way is
        shown: a frame the decoder has not caught up with is passed over."""
        camera = self._camera()
        if not self.playing or camera is None or not len(camera.index):
            self._halt()
            return
        offset, now = self._offset(), time.monotonic()
        place, self._play_start = playback.play_on(
            camera.index, self._play_start, now, offset
        )
        if place is None and camera.settings.get("record", True):
            self.go_live()  # caught up with the recording: it plays on live
        elif place is None:  # a file opened as it is has no Live: it ends
            self._halt()
            self._go(len(camera.index) - 1)
        elif not camera.pending and (place != self.place or camera.shown != place):
            # Due, or passed over while one was on its way; while one is, nothing
            # is done at all: a slow decoder is not raced by the whole window.
            self._go(place)

    def _show_play(self) -> None:
        self.play_button.setText("Pause" if self.live or self.playing else "Play")

    def _refresh(self, force: bool = False) -> None:
        kept = {
            c.id: (c.index.generation, self._frame_shown(c))
            for c in self.cameras.values()
        }
        grown = [other.index.refresh() for other in self.cameras.values()]
        for other in self.cameras.values():
            generation, frame = kept[other.id]
            if other.index.generation != generation and frame is not None:
                other.shown = other.index.find(frame)  # sorted anew
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
        elif self.place is not None:  # the frame shown, maybe at a new place, again
            self._go(self.place)

    def _frame_shown(self, camera: Camera) -> Frame | None:
        return None if camera.shown is None else camera.index.frame(camera.shown)

    def _go(self, place: int) -> None:
        """The video at ``place`` of the chosen camera, every camera following."""
        camera = self._camera()
        if camera is None:
            return
        self.place = place
        frame = camera.index.frame(place)
        moment = self.moment = frame.ms + self._offset()
        self.timeline.set_position(moment)
        clock = clock_of(self._line_ms(moment))
        self.time_label.setText(f"{clock} LIVE" if self.live else clock)
        source = int(self.session.get("source_offset_ms", 0))
        self.source_label.setText(f"source {source:+d} ms")
        if not self.playing or time.monotonic() - self._followed >= FOLLOW_S:
            # Following scans every line of both lists: at a seek, at once; while
            # playing, a few times a second, or a long race slows the playing.
            self._followed = time.monotonic()
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
            place = camera.index.nearest(target, within=NEAR_MS)
        if self.playing and camera.pending:
            # Playing: the frame due waits for the one on its way, so a decoder
            # slower than the camera shows every frame it can, each the one asked.
            return
        camera.shown = place
        if self._hidden_others() and camera is not self._camera():
            return  # hidden: decoded once it is shown again (004, FR-007)
        if place is None:
            camera.wanted, camera.pending = None, False
            if len(camera.index):
                camera.view.show_text("No frame at this moment")
            return
        frame = camera.index.frame(place)
        if (camera.id, frame) == camera.wanted:
            return
        camera.wanted = (camera.id, frame)  # the frame, not its place: places move
        camera.pending = True
        if not self.playing:  # a moving picture is not dimmed: it would flicker
            camera.view.show_waiting()  # no crossing timed on the frame before
        camera.worker.request(frame.path, frame.pts, camera.wanted)

    def _decoded(self, tag: tuple[str, Frame], image: QImage) -> None:
        """A frame decoded, handed over in this window's thread: a lambda would run
        in the decoder's, where no widget may be touched."""
        camera = self.cameras.get(tag[0])
        if camera is None or tag != camera.wanted:
            return  # an answer to a request since replaced, or a camera removed
        camera.pending = False
        if image.isNull():
            camera.view.show_text("This frame cannot be shown")
        else:
            camera.view.show_image(image)

    # -- cameras in step -------------------------------------------------------

    def mark_event(self) -> None:
        """The shared event at the frame shown (app/shared_event.py)."""
        camera = self._camera()
        if camera is None or self.place is None:
            self._say("Show the event on a camera first")
            return
        if not self._frame_on_screen():
            return
        name = self._name(camera.id)
        frame = camera.index.frame(self.place)
        self.shared_event, offset = shared_event.mark(
            self.shared_event,
            camera.id,
            frame.ms + self._offset(),
            frame.ms,
            time.monotonic(),
            set(self.cameras),
        )
        if offset is None:
            self._say(f"Event marked on {name}: now show it on the other cameras")
            return
        camera.settings["offset_ms"] = offset
        self._save_session()
        self._say(f"{name} is aligned on the event: {offset:+d} ms")
        self._refresh(force=True)
        self._go(self.place)
        self._show_suggestions()  # gathered and timed on the new offset

    def _offset(self) -> int:
        camera = self._camera()
        return 0 if camera is None else int(camera.settings.get("offset_ms", 0))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's name
        """The window goes; the recorders keep recording."""
        self.timer.stop()
        self.play_timer.stop()
        for job in (self._job, self._numbers_job):  # stopped, any answer ignored
            if job is not None:
                job.cancel()
        self._job = self._numbers_job = None
        for camera in self.cameras.values():
            camera.worker.stop()
            self._stop_analyzer(camera)
        super().closeEvent(event)


_OWN_FILE = "?file"  # the model list's last item: a file of the referee's own


class _StillCombo(QComboBox):
    """A list the wheel does not turn: scrolling past it in the middle of a race
    must not change the model, restarting every analyser or a download."""

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt's name
        event.ignore()


class _Fetch(QObject):
    """A model's download heard of through signals, which Qt hands to the window's
    thread; the download itself is models.Download."""

    progress = Signal(object, int)  # the download, bytes so far
    done = Signal(object, str)  # the download, what went wrong (empty: it is there)

    def start(self, model: models.Model) -> models.Download:
        job = models.Download(model, self.progress.emit, self.done.emit)
        job.start()
        return job


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
    environment = QProcessEnvironment()
    for key, value in child_environment().items():
        environment.insert(key, value)
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
