"""Adding a camera: its connection, and what that connection needs."""

from __future__ import annotations

import contextlib
import io
import ipaddress
import threading
from collections.abc import Sequence
from typing import Any

import segno
from PySide6.QtCore import Qt, QTimer, Signal
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
from app.recorder.testcam import SCENES

CONNECTION_NAMES = {  # the phone's streaming app first: the camera PhotoFinish expects
    "rtmp": "Phone streaming app, sending here (RTMP)",
    "rtsp": "Network stream a camera serves (RTSP)",
    "usb": "USB camera",
    "test": "Test camera",
    "file": "Video file",
}
NO_NETWORK = (
    "No network address found: join this computer and the phone to one network, "
    "or type this computer's address in the phone"
)
NETWORK_POLL_MS = 2000
_ROWS = {  # the fields each connection shows
    "usb": ("device", "size", "fps"),
    "rtsp": ("url", "transport"),
    "rtmp": ("port", "path", "lenses", "address", "qr"),
    "test": ("size", "fps", "scene"),
    "file": ("file", "live"),
}


class CameraDialog(QDialog):
    _found = Signal(str)  # this computer's address, looked up off the window's thread

    def __init__(
        self,
        parent: QWidget | None,
        camera_id: str,
        usb_names: list[str],
        others: Sequence[dict[str, Any]] = (),
        spare_ids: Sequence[str] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a camera")
        self.camera_id = camera_id
        self.spare_ids = list(spare_ids)  # free ids for a phone's other lenses
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
        self.port = _number(1, 65535, next(cameras.free_ports(taken)))
        self.path = QLineEdit(f"live/{camera_id}")
        self.lenses = {lens: QCheckBox(name) for lens, name in cameras.LENSES.items()}
        self.lenses["main"].setChecked(True)
        lens_row = QHBoxLayout()
        for tick in self.lenses.values():
            lens_row.addWidget(tick)
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
            "lenses": self._row("Lenses (PhotoFinish Camera)", lens_row),
            "address": self._row("Type in the streaming app", self.address),
            "qr": self._row("Or scan it with PhotoFinish Camera", self.qr),
            "scene": self._row("Scene", self.scene),
            "file": self._row("Video file", file_row),
            "live": self._row("", self.live),
        }
        self.form.addRow(self.problems)
        self.form.addRow(self.buttons)

        self._here: str | None = None  # this computer's address, looked up at the open
        # A computer with no network address yet is looked for again every 2 s, not at
        # every key typed: a lookup with no network may take a while.
        self._network = QTimer(self)
        self._network.setInterval(NETWORK_POLL_MS)
        self._network.timeout.connect(self._look_for_network)
        self._found.connect(self._network_found)
        self._closed = False  # the window keeps a closed dialog: its polling ends
        self.finished.connect(self._close_network)
        for box in (self.connection, self.device, self.transport, self.scene):
            box.currentTextChanged.connect(self._check)
        for line in (self.name, self.url, self.path, self.file):
            line.textChanged.connect(self._check)
        for spin in (self.width_box, self.height_box, self.port, self.fps):
            spin.valueChanged.connect(self._check)
        for lens in self.lenses.values():
            lens.toggled.connect(self._check)
        self._check()

    def kind(self) -> str:
        return str(self.connection.currentData())

    def camera(self) -> dict[str, Any]:
        """The camera as the session keeps it."""
        name = self.name.text().strip() or self.camera_id
        return self._made(self.camera_id, name, self._settings())

    def cameras(self) -> list[dict[str, Any]]:
        """The cameras to add: this one, or a phone's camera for each lens ticked --
        named after its lens, on the next free id, port and ``live/<id>`` path when
        there are several (004, FR-001), each noting its lens and its phone, the
        first lens's id (007, FR-012)."""
        lenses = self._lenses()
        first = self.camera()
        if self.kind() != "rtmp" or len(lenses) < 2:
            return [first]
        ids = [self.camera_id, *self.spare_ids]
        taken = cameras.ports_taken(self.others)
        return [
            self._made(
                camera_id, f"{first['name']} {cameras.LENSES[lens].lower()}", made
            )
            | {"lens": lens, "phone": self.camera_id}
            for lens, camera_id, made in cameras.lens_cameras(
                lenses, ids, first["settings"], taken
            )
        ]

    def _made(
        self, camera_id: str, name: str, settings: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "id": camera_id,
            "name": name,
            "connection": self.kind(),
            "settings": settings,
            "finish_line": [[0.5, 0.0], [0.5, 1.0]],
            "offset_ms": 0,
            "record": self.kind() != "file" or self.live.isChecked(),
        }

    def _lenses(self) -> list[str]:
        return [lens for lens, box in self.lenses.items() if box.isChecked()]

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
        clash = cameras.port_clash(self.camera(), self.others)
        if self.kind() == "rtmp":
            self._show_address(self._settings(), clash)
        found = cameras.problems(self.camera())
        if self.kind() == "rtmp" and clash:
            found.append(clash)
        if self.kind() == "rtmp" and not self._lenses():
            found.append("no lens ticked: tick the ones the phone is to stream")
        if self.kind() == "rtmp" and len(self._lenses()) > 1 + len(self.spare_ids):
            found.append("not as many free camera ids as lenses ticked")
        self.problems.setText("\n".join(found))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not found)

    def _show_address(self, settings: dict[str, Any], clash: str | None) -> None:
        """The address to stream to, as text and as a QR code for the phone -- a
        line per lens when several are ticked: none while the settings are wrong,
        no lens is ticked or the port is another phone's, which a phone scanning it
        would stream to; a word instead while this computer has no network address,
        which would send the phone to itself. A lens other than Main keeps its line
        typed too: PhotoFinish Camera takes an address alone for Main's."""
        text, scannable = "", False
        lenses = self._lenses()
        if (
            lenses
            and not clash
            and not cameras.problems({"connection": "rtmp", "settings": settings})
        ):
            if self._here is None:
                self._here = cameras.this_computer()
            here = self._here
            scannable = not ipaddress.ip_address(here).is_loopback
            streams = [
                (lens, cameras.rtmp_url(made["settings"], here))
                for lens, made in zip(lenses, self.cameras(), strict=False)
            ]
            text = cameras.pairing_text(streams) if scannable else NO_NETWORK
            if not scannable and not self._network.isActive():
                self._network.start()
        if text == self.address.text():  # every key typed comes here
            return
        self.address.setText(text)
        if scannable:
            self.qr.setPixmap(qr_pixmap(text))
        else:
            self.qr.clear()

    def _look_for_network(self) -> None:
        """This computer's address looked for again, as it may have joined a network:
        off the window's thread, as a lookup with no network may take a while."""
        self._network.stop()
        if not self._closed:
            threading.Thread(target=self._look_up, daemon=True).start()

    def _close_network(self) -> None:
        self._closed = True
        self._network.stop()

    def _look_up(self) -> None:
        here = cameras.this_computer()
        with contextlib.suppress(RuntimeError):  # the dialog closed meanwhile
            self._found.emit(here)

    def _network_found(self, here: str) -> None:
        if not self._closed:
            self._here = here
            self._check()

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
