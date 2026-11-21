"""Exporting cameras' video, a file each (specs/011-video-export): the cameras to
tick, and the job that writes their files on a thread of its own."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app import export


class ExportChoice(QDialog):
    """The cameras with video to export, all ticked at first."""

    def __init__(self, parent: QWidget | None, names: dict[str, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export video")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("A file for each camera ticked, in a folder chosen next.")
        )
        self.ticks: dict[str, QCheckBox] = {}
        for camera_id, name in names.items():
            tick = QCheckBox(name)
            tick.setChecked(True)
            layout.addWidget(tick)
            self.ticks[camera_id] = tick
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self) -> list[str]:
        return [camera_id for camera_id, tick in self.ticks.items() if tick.isChecked()]


def choose_cameras(parent: QWidget | None, names: dict[str, str]) -> list[str]:
    """The cameras ticked; none when the referee cancels."""
    dialog = ExportChoice(parent, names)
    try:
        return dialog.chosen() if dialog.exec() == QDialog.DialogCode.Accepted else []
    finally:
        dialog.deleteLater()  # not one more hidden dialog kept for each export


class ExportJob(QObject):
    """The cameras' files written one after another on a thread of its own, heard of
    through signals, which Qt hands to the window's thread."""

    progress = Signal(int)  # the share done, of export.STEPS
    # The files written; what went wrong, "" for nothing; the pieces left unreadable.
    done = Signal(object, str, int)

    def __init__(self, jobs: list[tuple[Path, Path]]) -> None:
        super().__init__()
        self.jobs = jobs
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()

    def stop(self, wait_s: float) -> None:
        """Cancelled, waited for up to ``wait_s``: the program closing removes the
        file under way rather than leaving it half written -- unless a piece takes
        longer than that to read, its ``<name>.mp4.part`` then left, named as not
        finished, and taken by no later export."""
        self.cancel()
        if self._thread.is_alive():
            self._thread.join(wait_s)

    def _run(self) -> None:
        written, error, skipped = export.export_all(
            self.jobs, self.progress.emit, self._stop.is_set
        )
        self.done.emit(written, error, skipped)
