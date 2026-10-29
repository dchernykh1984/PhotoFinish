"""A camera's frame, scaled to fit with its proportions, with the camera's finish
line and the points the referee clicked on this frame drawn over it."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.analysis import Zone
from app.interpolation import Line, Point


class CameraView(QWidget):
    """Shows one frame; a line of text when there is none."""

    clicked = Signal(object)  # a point of the picture, 0-1 coordinates

    def __init__(self) -> None:
        super().__init__()
        self.image = QImage()
        self.text = "No video yet"
        self.line: Line | None = None
        self.marks: list[Point] = []
        self.zone: Zone | None = None
        self.chosen = False  # the camera the keys step through: framed
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def show_image(self, image: QImage) -> None:
        self.image = image
        self.update()

    def show_text(self, text: str) -> None:
        """No frame to show: say why."""
        self.image, self.text = QImage(), text
        self.update()

    def show_marks(
        self, line: Line | None, marks: list[Point], zone: Zone | None = None
    ) -> None:
        """The finish line, the points clicked on the frame shown, and the zone
        riders are looked for in, while that is on."""
        self.line, self.marks, self.zone = line, marks, zone
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

    def to_picture(self, at: QPointF) -> Point | None:
        """A point of the widget in the picture's 0-1 coordinates; None off it."""
        rect = self.image_rect()
        if rect.isNull() or not rect.contains(at):
            return None
        return (
            (at.x() - rect.left()) / rect.width(),
            (at.y() - rect.top()) / rect.height(),
        )

    def to_widget(self, point: Point) -> QPointF:
        rect = self.image_rect()
        return QPointF(
            rect.left() + point[0] * rect.width(), rect.top() + point[1] * rect.height()
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's name
        point = self.to_picture(event.position())
        if event.button() == Qt.MouseButton.LeftButton and point is not None:
            self.clicked.emit(point)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))
        if self.image.isNull():
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text)
            painter.end()
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.image_rect(), self.image)
        if self.line is not None:
            painter.setPen(QPen(QColor(230, 40, 40), 2))
            painter.drawLine(self.to_widget(self.line[0]), self.to_widget(self.line[1]))
        if self.zone is not None:
            painter.setPen(QPen(QColor(80, 200, 255), 1, Qt.PenStyle.DashLine))
            corners = QRectF(self.to_widget(self.zone[0]), self.to_widget(self.zone[1]))
            painter.drawRect(corners)
        painter.setPen(QPen(QColor(255, 210, 0), 2))
        for mark in self.marks:
            centre = self.to_widget(mark)
            painter.drawEllipse(centre, 6, 6)
            painter.drawPoint(centre)
        if self.chosen:
            painter.setPen(QPen(QColor(80, 160, 255), 3))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
        painter.end()
