"""Where a rider is in view, from motion (specs/002-video-analysis, no model).

Frames are looked at in grey, 160 pixels wide, inside the zone around the finish
line. A pixel moves when it differs from a background learned slowly where nothing
moves. A moment counts when moving pixels cover more than 0.5% of the zone and
their centre has travelled at least a quarter of the zone across the finish line
within the last 2 s: a rider crosses the zone, leaves sway in place. When the moving
area falls to under half of what it was, the one who moved has gone: the travel is
measured afresh from there, so leaves swaying after a rider do not lengthen its
stretch.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from app.analysis import Zone
from app.interpolation import Line

WIDTH = 160  # frames are looked at this wide
THRESHOLD = 25.0  # grey levels a moving pixel differs by
LEAST_AREA = 0.005  # of the zone
TRAVEL_SHARE = 0.25  # of the zone, across the line
TRAVEL_MS = 2000
LEARN = 0.05  # how fast the background follows where nothing moves
LEARN_MOVING = 0.002  # and where something does: a rider passes, a car parks


class Motion:
    """Moments a rider is in view, fed one grey frame at a time."""

    def __init__(self, zone: Zone, line: Line) -> None:
        self.zone, self.line = zone, line
        self._background: np.ndarray | None = None
        self._track: deque[tuple[int, float]] = deque()  # moment, centre across
        self._area = 0.0  # the moving share of the zone in the frame before

    def feed(self, grey: np.ndarray, ms: int) -> int | None:
        """A frame (grey, WIDTH wide) at ``ms``: when it shows a rider, the moment
        that rider's crossing of the zone began; else None."""
        height, width = grey.shape
        left, top, right, bottom = self._bounds(width, height)
        part = grey[top:bottom, left:right].astype(np.float32)
        if self._background is None or self._background.shape != part.shape:
            self._background, self._track, self._area = part, deque(), 0.0
            return None
        change = part - self._background
        moving = np.abs(change) > THRESHOLD
        self._background += np.where(moving, LEARN_MOVING, LEARN) * change
        while self._track and ms - self._track[0][0] > TRAVEL_MS:
            self._track.popleft()
        area, before = float(moving.mean()), self._area
        self._area = area
        if area < LEAST_AREA or area < before / 2:
            self._track.clear()  # nothing moves, or the one who moved has gone
        if area < LEAST_AREA:
            return None
        across = self._across(width, height)
        rows, columns = np.nonzero(moving)
        x, y = columns.mean() + left, rows.mean() + top
        self._track.append((ms, float(x * across[0] + y * across[1])))
        places = [place for _, place in self._track]
        reach = self._reach(width, height, across)
        if max(places) - min(places) < TRAVEL_SHARE * reach:
            return None
        return self._track[0][0]

    def _bounds(self, width: int, height: int) -> tuple[int, int, int, int]:
        """The zone in pixels: left, top, right, bottom; never empty."""
        (x0, y0), (x1, y1) = self.zone
        left, top = round(x0 * width), round(y0 * height)
        return (
            left,
            top,
            max(round(x1 * width), left + 1),
            max(round(y1 * height), top + 1),
        )

    def _across(self, width: int, height: int) -> tuple[float, float]:
        """The unit direction across the finish line, in pixels."""
        (xa, ya), (xb, yb) = self.line
        dx, dy = (xb - xa) * width, (yb - ya) * height
        length = math.hypot(dx, dy) or 1.0
        return -dy / length, dx / length

    def _reach(self, width: int, height: int, across: tuple[float, float]) -> float:
        """How far the zone reaches across the line, in pixels."""
        (x0, y0), (x1, y1) = self.zone
        corners = [(x * width, y * height) for x in (x0, x1) for y in (y0, y1)]
        places = [x * across[0] + y * across[1] for x, y in corners]
        return max(places) - min(places)


class Stretches:
    """Moments with a rider gathered into stretches of time."""

    def __init__(self, join_ms: int = 1000) -> None:
        self.join_ms = join_ms
        self.found: list[list[int]] = []

    def add(self, ms: int, since: int | None) -> None:
        """The frame at ``ms`` shows a rider since ``since``, or none (None)."""
        if since is None:
            return
        last = self.found[-1] if self.found else None
        if last is not None and since <= last[1] + self.join_ms:
            last[1] = max(last[1], ms)
            return
        self.found.append([since, ms])
