"""Exporting cameras' video, a file each (specs/011-video-export): the cameras to
tick, and the job that writes their files on a thread of its own."""

from __future__ import annotations

import re
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

CANCELLED = "cancelled"
STEPS = 1000  # the progress's whole


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
    return dialog.chosen() if dialog.exec() == QDialog.DialogCode.Accepted else []


def file_name(name: str) -> str:
    """A camera's name as a file's: what a file's name cannot hold replaced."""
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .") or "camera"


class ExportJob(QObject):
    """The cameras' files written one after another on a thread of its own, heard of
    through signals, which Qt hands to the window's thread."""

    progress = Signal(int)  # the share done, of STEPS
    # The files written; what went wrong, "" for nothing; the pieces left unreadable.
    done = Signal(object, str, int)

    def __init__(self, jobs: list[tuple[Path, Path]]) -> None:
        super().__init__()
        self.jobs = jobs
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        written: list[Path] = []  # each file as it is done: those a stop leaves too
        skipped: list[Path] = []
        error = ""
        count = len(self.jobs)
        try:
            for n, (folder, target) in enumerate(self.jobs):

                def told(done: int, total: int, n: int = n) -> None:
                    self.progress.emit(
                        (n * STEPS + done * STEPS // max(total, 1)) // count
                    )

                export.export(folder, target, told, self._stop.is_set, written, skipped)
        except export.CancelledError:
            error = CANCELLED
        except Exception as failure:
            error = str(failure) or type(failure).__name__
        self.done.emit(written, error, len(skipped))
