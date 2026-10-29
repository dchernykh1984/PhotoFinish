"""The number the referee types: Enter adds the crossing, while the keys that move
through the video keep working with the field in focus (FR-016)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit

# Keys the window's shortcuts use; a field would keep them for its cursor.
PASSED_ON = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_L)


class NumberField(QLineEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("Number, then Enter")
        self.setMaxLength(32)

    def event(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and event.key() in PASSED_ON
        ):
            event.ignore()  # the window's shortcut gets it
            return True
        return super().event(event)
