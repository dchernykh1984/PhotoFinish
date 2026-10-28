"""The PhotoFinish main window.

Empty for now: the first feature is specified in
specs/001-video-refinement/spec.md and built in later changes.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Top-level window; the video workspace will live here."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PhotoFinish")
