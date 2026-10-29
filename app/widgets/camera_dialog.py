"""Adding a camera: a preset or a connection, and what that connection needs."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
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
from app.cameras import PRESETS, RTMP_PORT
from app.recorder.testcam import SCENES

CONNECTION_NAMES = {
    "usb": "USB camera",
    "rtsp": "Network stream the camera serves (RTSP)",
    "rtmp": "Stream the camera sends here (RTMP)",
    "test": "Test camera",
    "file": "Video file played as live",
}
_ROWS = {  # the fields each connection shows
    "usb": ("device", "size", "fps"),
    "rtsp": ("url", "transport"),
    "rtmp": ("port", "path", "address"),
    "test": ("size", "fps", "scene"),
    "file": ("file",),
}


class CameraDialog(QDialog):
    def __init__(
        self, parent: QWidget | None, camera_id: str, usb_names: list[str]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a camera")
        self.camera_id = camera_id
        self.name = QLineEdit(f"Camera {camera_id.removeprefix('cam')}")
        self.preset = QComboBox()
        self.preset.addItem("None", None)
        for preset in PRESETS:
            self.preset.addItem(preset.label, preset.id)
        self.connection = QComboBox()
        for key, label in CONNECTION_NAMES.items():
            self.connection.addItem(label, key)
        self.connection.setCurrentIndex(list(CONNECTION_NAMES).index("test"))
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
        self.port = _number(1, 65535, RTMP_PORT)
        self.path = QLineEdit(f"live/{camera_id}")
        self.address = QLabel()
        self.scene = QComboBox()
        self.scene.addItems(SCENES)
        self.scene.setCurrentText("bar")
        self.file = QLineEdit()
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
        self.form.addRow("Preset", self.preset)
        self.form.addRow("Connection", self.connection)
        self._rows = {
            "device": self._row("Camera", self.device),
            "size": self._row("Picture size", size_row),
            "fps": self._row("Frames a second", self.fps),
            "url": self._row("Stream address", self.url),
            "transport": self._row("Transport", self.transport),
            "port": self._row("Port", self.port),
            "path": self._row("Stream path", self.path),
            "address": self._row("Type in the camera app", self.address),
            "scene": self._row("Scene", self.scene),
            "file": self._row("Video file", file_row),
        }
        self.form.addRow(self.problems)
        self.form.addRow(self.buttons)

        self.preset.currentIndexChanged.connect(self._apply_preset)
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
            "preset": self.preset.currentData(),
            "finish_line": [[0.5, 0.0], [0.5, 1.0]],
            "offset_ms": 0,
            "record": True,
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

    def _apply_preset(self) -> None:
        preset = next((p for p in PRESETS if p.id == self.preset.currentData()), None)
        if preset is None:
            return
        self.connection.setCurrentIndex(list(CONNECTION_NAMES).index(preset.connection))
        settings = preset.settings
        if "device" in settings:
            self.device.setCurrentText(settings["device"])
        if "width" in settings:
            self.width_box.setValue(settings["width"])
            self.height_box.setValue(settings["height"])
        if "fps" in settings:
            self.fps.setValue(settings["fps"])
        self.url.setText(settings.get("url", self.url.text()))
        self.port.setValue(settings.get("port", self.port.value()))
        self.path.setText(settings.get("path", self.path.text()))
        if not self.name.text().startswith(preset.name):
            self.name.setText(preset.name)

    def _check(self) -> None:
        shown = _ROWS[self.kind()]
        for key, row in self._rows.items():
            self.form.setRowVisible(row, key in shown)
        if self.kind() == "rtmp":
            settings = self._settings()
            if cameras.problems({"connection": "rtmp", "settings": settings}):
                self.address.setText("")
            else:
                self.address.setText(
                    cameras.rtmp_url(settings, cameras.this_computer())
                )
        found = cameras.problems(self.camera())
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


def _number(least: int, most: int, value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(least, most)
    box.setValue(value)
    return box
