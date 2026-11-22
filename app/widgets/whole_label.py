"""A label whose text wraps, held whole."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
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
        if text != self.text():  # said again at every poll: nothing asked of the window
            super().setText(text)
            self._hold()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():  # its text wraps anew
            self._hold()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt's name
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._hold()  # a style's font, given after the text: as high as it is now

    def _hold(self) -> None:
        # Once laid out: the width it had before is none it is shown at, and the
        # window, made as high as that asks, would stay so.
        if self.testAttribute(Qt.WidgetAttribute.WA_Resized):
            # Measured with no least of its own: QLabel gives none under it, and the
            # height once held would be held for good. -1: never given a text.
            self.setMinimumHeight(0)
            self.setMinimumHeight(max(self.heightForWidth(self.width()), 0))
