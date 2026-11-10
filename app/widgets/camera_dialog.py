"""Adding a camera: its connection, and what that connection needs."""

from __future__ import annotations

import io
import itertools
from collections.abc import Sequence
from typing import Any

import segno
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from app import cameras
from app.cameras import RTMP_PORT
from app.recorder.testcam import SCENES

CONNECTION_NAMES = {  # the phone's streaming app first: the camera PhotoFinish expects
    "rtmp": "Phone streaming app, sending here (RTMP)",
    "rtsp": "Network stream a camera serves (RTSP)",
    "usb": "USB camera",
    "test": "Test camera",
    "file": "Video file",
}
_ROWS = {  # the fields each connection shows
    "usb": ("device", "size", "fps"),
    "rtsp": ("url", "transport"),
    "rtmp": ("port", "path", "address", "qr"),
    "test": ("size", "fps", "scene"),
    "file": ("file", "live"),
}


class CameraDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        camera_id: str,
        usb_names: list[str],
        others: Sequence[dict[str, Any]] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a camera")
        self.camera_id = camera_id
        self.name = QLineEdit(f"Camera {camera_id.removeprefix('cam')}")
        self.connection = QComboBox()
        for key, label in CONNECTION_NAMES.items():
            self.connection.addItem(label, key)
        self.connection.setCurrentIndex(list(CONNECTION_NAMES).index("rtmp"))
        self.device = QComboBox()
        self.device.setEditable(True)
        self.device.addItems(usb_names)
        self.width_box, self.height_box = (
            _number(64, 7680, 1280),
            _number(64, 4320, 720),
        )
        self.width_box.setSingleStep(2)
        self.height_box.setSingleStep(2)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(1, 240)
        self.fps.setValue(30)
        self.url = QLineEdit()
        self.transport = QComboBox()
        self.transport.addItems(["tcp", "udp"])
        self.others = list(others)  # the session's cameras: their ports are taken
        taken = cameras.ports_taken(self.others)
        free = next(p for p in itertools.count(RTMP_PORT) if p not in taken)
        self.port = _number(1, 65535, free)
        self.path = QLineEdit(f"live/{camera_id}")
        self.address = QLabel()
        self.address.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.qr = QLabel()
        self.scene = QComboBox()
        self.scene.addItems(SCENES)
        self.scene.setCurrentText("bar")
        self.file = QLineEdit()
        self.live = QCheckBox("Play it as if a camera filmed it now, recording it")
        self.live.setToolTip(
            "Unchecked: a camera's own recording, opened as it is and aligned after "
            "the race"
        )
        browse = QPushButton("Choose...")
        browse.clicked.connect(self._choose_file)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file)
        file_row.addWidget(browse)
        size_row = QHBoxLayout()
        size_row.addWidget(self.width_box)
        size_row.addWidget(QLabel("x"))
        size_row.addWidget(self.height_box)
        self.problems = QLabel()
        self.problems.setStyleSheet("color: #c03030")
        self.problems.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.form = QFormLayout(self)
        self.form.addRow("Name", self.name)
        self.form.addRow("Connection", self.connection)
        self._rows = {
            "device": self._row("Camera", self.device),
            "size": self._row("Picture size", size_row),
            "fps": self._row("Frames a second", self.fps),
            "url": self._row("Stream address", self.url),
            "transport": self._row("Transport", self.transport),
            "port": self._row("Port", self.port),
            "path": self._row("Stream path", self.path),
            "address": self._row("Type in the streaming app", self.address),
            "qr": self._row("Or scan it with PhotoFinish Camera", self.qr),
            "scene": self._row("Scene", self.scene),
            "file": self._row("Video file", file_row),
            "live": self._row("", self.live),
        }
        self.form.addRow(self.problems)
        self.form.addRow(self.buttons)

        self._here: str | None = None  # this computer's address, looked up once
        for box in (self.connection, self.device, self.transport, self.scene):
            box.currentTextChanged.connect(self._check)
        for line in (self.name, self.url, self.path, self.file):
            line.textChanged.connect(self._check)
        for spin in (self.width_box, self.height_box, self.port, self.fps):
            spin.valueChanged.connect(self._check)
        self._check()

    def kind(self) -> str:
        return str(self.connection.currentData())

    def camera(self) -> dict[str, Any]:
        """The camera as the session keeps it."""
        return {
            "id": self.camera_id,
            "name": self.name.text().strip() or self.camera_id,
            "connection": self.kind(),
            "settings": self._settings(),
            "finish_line": [[0.5, 0.0], [0.5, 1.0]],
            "offset_ms": 0,
            "record": self.kind() != "file" or self.live.isChecked(),
        }

    def _settings(self) -> dict[str, Any]:
        kind = self.kind()
        size = {"width": self.width_box.value(), "height": self.height_box.value()}
        fps = self.fps.value()
        if kind == "usb":
            return {"device": self.device.currentText().strip(), **size, "fps": fps}
        if kind == "rtsp":
            return {
                "url": self.url.text().strip(),
                "transport": self.transport.currentText(),
            }
        if kind == "rtmp":
            return {"port": self.port.value(), "path": self.path.text().strip()}
        if kind == "test":
            return {**size, "fps": fps, "scene": self.scene.currentText()}
        return {"path": self.file.text().strip()}

    def _check(self) -> None:
        shown = _ROWS[self.kind()]
        for key, row in self._rows.items():
            self.form.setRowVisible(row, key in shown)
        if self.kind() == "rtmp":
            settings = self._settings()
            if cameras.problems({"connection": "rtmp", "settings": settings}):
                self.address.setText("")
                self.qr.clear()
            else:
                self._here = self._here or cameras.this_computer()
                url = cameras.rtmp_url(settings, self._here)
                if url != self.address.text():  # every key typed comes here
                    self.address.setText(url)
                    self.qr.setPixmap(qr_pixmap(url))
        found = cameras.problems(self.camera())
        clash = cameras.port_clash(self.camera(), self.others)
        if self.kind() == "rtmp" and clash:
            found.append(clash)
        self.problems.setText("\n".join(found))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not found)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "A video file", "", "Video (*.*)")
        if path:
            self.file.setText(path)

    def _row(self, label: str, field: QWidget | QHBoxLayout) -> int:
        self.form.addRow(label, field)
        return self.form.rowCount() - 1


def qr_pixmap(text: str) -> QPixmap:
    """``text`` as a QR code for the phone to scan: a full-size one, as a phone's
    scanner may not read the micro kind."""
    png = io.BytesIO()
    segno.make_qr(text, error="m").save(png, kind="png", scale=5, border=2)
    pixmap = QPixmap()
    pixmap.loadFromData(png.getvalue(), "PNG")
    return pixmap


def _number(least: int, most: int, value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(least, most)
    box.setValue(value)
    return box
