"""The recording on a line: gaps shaded, the position marked, frames ticked when
zoomed in. The wheel zooms around the pointer; a click moves the video there. Zoomed
in until a frame interval is at least 100 pixels wide, a click between two frames
picks that moment instead (US5)."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QWheelEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

LEAST_VIEW_MS = 100  # zoomed all the way in: a few frames across the widget
PICK_PX = 100  # a frame interval this wide: a click picks a moment between frames
GAP_MS = 1000  # frames further apart have a gap between them, not a frame interval
_TICKS_PX = 4  # frames are ticked once they are this far apart


class Timeline(QWidget):
    seek = Signal(object)  # a moment on the video's time, Unix ms: past 32 bits
    picked = Signal(object)  # a moment picked between two frames, ms

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.start = self.end = 0  # the recording's span
        self.view = (0, 1)  # the span the widget shows
        self.position: int | None = None
        self.frames = np.empty(0, np.int64)
        self.offset = 0  # frames + offset: the video's time
        self.gaps: list[tuple[int, int]] = []
        self.stretches: list[tuple[int, int]] = []  # riders in view (002)
        self.zoomed = False
        self.following = True  # the view slides with the newest frame (Live)

    def set_recording(
        self, frames: np.ndarray, gaps: list[tuple[int, int]], offset: int = 0
    ) -> None:
        """The frames recorded (moments on their camera's clock, ascending), the gaps
        between them, and what puts them on the video's time: added as drawn, never
        to a copy of every frame."""
        self.frames, self.gaps, self.offset = frames, gaps, offset
        self.start, self.end = (
            (int(frames[0]) + offset, int(frames[-1]) + offset)
            if frames.size
            else (0, 0)
        )
        if not self.zoomed:
            self.view = (self.start, max(self.end, self.start + 1))
        elif self.following:
            length = self.view[1] - self.view[0]
            self.view = (self.end - length, self.end)
        self.update()

    def set_stretches(self, stretches: list[tuple[int, int]]) -> None:
        """Where the analysis saw a rider, drawn above the recording."""
        self.stretches = stretches
        self.update()

    def set_position(self, ms: int | None) -> None:
        self.position = ms
        self.update()

    def ms_at(self, x: float) -> int:
        start, end = self.view
        return round(start + (end - start) * x / max(self.width(), 1))

    def x_at(self, ms: float) -> float:
        start, end = self.view
        return (ms - start) * self.width() / max(end - start, 1)

    def zoom(self, factor: float, around_x: float) -> None:
        """The view ``factor`` times as long, the moment under ``around_x`` kept."""
        start, end = self.view
        whole = max(self.end - self.start, LEAST_VIEW_MS)
        length = min(max((end - start) * factor, LEAST_VIEW_MS), whole)
        anchor = self.ms_at(around_x)
        share = around_x / max(self.width(), 1)
        first = anchor - length * share
        first = min(max(first, self.start), max(self.end - length, self.start))
        self.view = (round(first), round(first + length))
        self.zoomed = length < whole
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt's name
        notches = event.angleDelta().y() / 120
        if notches:
            self.zoom(0.8**notches, event.position().x())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's name
        if event.button() != Qt.MouseButton.LeftButton:
            return
        ms = self.ms_at(event.position().x())
        if self.between_frames(ms):
            self.picked.emit(ms)
        else:
            self.seek.emit(ms)

    def between_frames(self, ms: int) -> bool:
        """True when ``ms`` lies between two frames shown at least PICK_PX apart, not
        in a gap of the recording: nothing was filmed there to pick."""
        after = int(np.searchsorted(self.frames, ms - self.offset))
        if after == 0 or after >= self.frames.size:
            return False
        first, second = int(self.frames[after - 1]), int(self.frames[after])
        if second - first > GAP_MS or any(a <= ms <= b for a, b in self.gaps):
            return False
        return self.x_at(second) - self.x_at(first) >= PICK_PX

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        painter = QPainter(self)
        height = self.height()
        painter.fillRect(self.rect(), QColor(45, 45, 45))
        if self.frames.size:
            x1, x2 = self.x_at(self.start), self.x_at(self.end)
            painter.fillRect(
                round(x1), 8, round(x2 - x1) + 1, height - 16, QColor(70, 110, 70)
            )
        for gap_start, gap_end in self.gaps:
            x1, x2 = self.x_at(gap_start), self.x_at(gap_end)
            painter.fillRect(
                round(x1), 8, round(x2 - x1) + 1, height - 16, QColor(140, 60, 60)
            )
        for start, end in self.stretches:
            x1, x2 = self.x_at(start), self.x_at(end)
            painter.fillRect(
                round(x1), 2, max(round(x2 - x1), 2), 6, QColor(80, 160, 255)
            )
        self._tick_frames(painter)
        if self.position is not None:
            painter.setPen(QColor(255, 210, 0))
            x = self.x_at(self.position)
            painter.drawLine(QPointF(x, 0), QPointF(x, height))
        painter.end()

    def _tick_frames(self, painter: QPainter) -> None:
        start, end = self.view
        lo, hi = np.searchsorted(self.frames, [start - self.offset, end - self.offset])
        shown = self.frames[lo:hi]
        if shown.size < 2 or self.width() / shown.size < _TICKS_PX:
            return
        painter.setPen(QColor(220, 220, 220))
        for ms in shown:
            x = self.x_at(int(ms) + self.offset)
            painter.drawLine(
                QPointF(x, self.height() - 14), QPointF(x, self.height() - 4)
            )
