"""A label whose text wraps, held whole."""

from __future__ import annotations

from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel


class WholeLabel(QLabel):
    """A wrapped label held whole: at least as high as its text at its width, so its
    window's height makes room for it -- a layout's minimum leaves a wrapped text's
    height out, and what is below would be pressed under its own."""

    def __init__(self) -> None:
        super().__init__()
        self.setWordWrap(True)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt's name
        super().setText(text)
        self._hold()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self._hold()

    def _hold(self) -> None:
        if self.isVisible():  # laid out: its width is the one it is shown at
            self.setMinimumHeight(self.heightForWidth(self.width()))
