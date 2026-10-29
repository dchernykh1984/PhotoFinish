"""The PhotoFinish main window: layout and wiring. What is not drawing lives in the
Qt-free modules (session, video_index, recorder) and the widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
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
from app.lines import scale_time, to_line_scale
from app.recorder import folder_of
from app.recorder.launcher import Watchdog, describe, heartbeat
from app.video_index import VideoIndex
from app.widgets.camera_dialog import CameraDialog
from app.widgets.camera_view import CameraView
from app.widgets.decode_worker import DecodeWorker
from app.widgets.timeline import Timeline

POLL_MS = 500


@dataclass
class Camera:
    """A camera of the session with its recording and its recorder."""

    settings: dict[str, Any]
    index: VideoIndex
    watchdog: Watchdog
    item: QListWidgetItem

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
        self._wanted: tuple[str, int] | None = None

        self.view = CameraView()
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek_ms)
        self.time_label = QLabel("--:--:--.---")
        self.camera_list = QListWidget()
        self.camera_list.setWordWrap(True)
        self.camera_list.currentRowChanged.connect(self._choose_camera)
        self.worker = DecodeWorker()
        self.worker.decoded.connect(self._show)

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
        video = QVBoxLayout()
        video.addWidget(self.view, stretch=1)
        video.addWidget(self.timeline)
        video.addLayout(transport)
        left = QWidget()
        left.setLayout(video)

        add, remove = QPushButton("Add..."), QPushButton("Remove")
        add.clicked.connect(self.add_camera)
        remove.clicked.connect(self.remove_camera)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        side = QVBoxLayout()
        side.addWidget(QLabel("Cameras"))
        side.addWidget(self.camera_list)
        side.addLayout(buttons)
        right = QWidget()
        right.setLayout(side)
        right.setMinimumWidth(260)

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
        self.session["cameras"] = [
            c for c in self.session["cameras"] if c.get("id") != camera.id
        ]
        session.save(self.session)
        del self.cameras[camera.id]
        self.camera_list.takeItem(self.camera_list.row(camera.item))
        if not self.cameras:
            self._choose_camera(-1)

    def _add(self, settings: dict[str, Any]) -> None:
        camera_id = str(settings["id"])
        item = QListWidgetItem(str(settings.get("name", camera_id)))
        item.setData(Qt.ItemDataRole.UserRole, camera_id)
        self.camera_list.addItem(item)
        camera = Camera(
            settings, VideoIndex(folder_of(camera_id)), Watchdog(camera_id), item
        )
        self.cameras[camera_id] = camera
        if settings.get("record", True):
            camera.watchdog.start()
        self._label(camera)

    def _free_id(self) -> str:
        n = 1
        while f"cam{n}" in self.cameras or folder_of(f"cam{n}").exists():
            n += 1
        return f"cam{n}"

    def _choose_camera(self, row: int) -> None:
        item = self.camera_list.item(row) if row >= 0 else None
        self.current = (
            None if item is None else str(item.data(Qt.ItemDataRole.UserRole))
        )
        self.place, self.live = None, True
        self.timeline.zoomed, self.timeline.following = False, True
        self.view.show_text("No video yet" if self.current else "Add a camera")
        self._refresh(force=True)

    def _camera(self) -> Camera | None:
        return None if self.current is None else self.cameras.get(self.current)

    # -- moving through the video ----------------------------------------------

    def poll(self) -> None:
        for camera in self.cameras.values():
            self._label(camera)
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
        camera = self._camera()
        if camera is None:
            self.timeline.set_recording(np.empty(0, np.int64), [])
            return
        if not camera.index.refresh() and not force:
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
        line_ms = to_line_scale(moment, bool(self.session.get("summer_time")))
        clock = scale_time(line_ms).split(" ")[1]
        self.time_label.setText(f"{clock} LIVE" if self.live else clock)
        self._wanted = (camera.id, place)
        self.worker.request(frame.path, frame.pts, self._wanted)

    def _show(self, tag: tuple[str, int], image: QImage) -> None:
        if tag == self._wanted and not image.isNull():
            self.view.show_image(image)

    def _offset(self) -> int:
        camera = self._camera()
        return 0 if camera is None else int(camera.settings.get("offset_ms", 0))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's name
        """The window goes; the recorders keep recording."""
        self.timer.stop()
        self.worker.stop()
        super().closeEvent(event)


def usb_cameras() -> list[str]:
    """The names of the cameras on this computer, as the system lists them."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
    except ImportError:  # pragma: no cover - a Qt without multimedia
        return []
    return [device.description() for device in QMediaDevices.videoInputs()]
