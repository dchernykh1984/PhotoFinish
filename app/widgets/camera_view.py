"""A camera's frame, scaled to fit with its proportions."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget


class CameraView(QWidget):
    """Shows one frame; a line of text when there is none."""

    def __init__(self) -> None:
        super().__init__()
        self.image = QImage()
        self.text = "No video yet"
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def show_image(self, image: QImage) -> None:
        self.image = image
        self.update()

    def show_text(self, text: str) -> None:
        """No frame to show: say why."""
        self.image, self.text = QImage(), text
        self.update()

    def image_rect(self) -> QRectF:
        """Where the frame is drawn: as large as fits, centred, proportions kept."""
        if self.image.isNull():
            return QRectF()
        scale = min(
            self.width() / self.image.width(), self.height() / self.image.height()
        )
        width, height = self.image.width() * scale, self.image.height() * scale
        return QRectF(
            (self.width() - width) / 2, (self.height() - height) / 2, width, height
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))
        if self.image.isNull():
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text)
        else:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(self.image_rect(), self.image)
        painter.end()
