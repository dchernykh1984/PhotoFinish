"""Riders followed from sample to sample, and the moment one crosses the line (002).

Boxes of two samples are matched greedily, nearest centres first: half a second
apart a fast rider's boxes do not overlap. A rider's front is the edge of its box
that leads across the finish line. When a front changes side of the
line between two samples, the frames between them are looked at again and the two
around the crossing give its moment, interpolated as 001's caliper does.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.analysis.detector import Box, iou
from app.interpolation import Line, Point, between, crossing, side

LEAST_OVERLAP = 0.1  # boxes of one rider in two frames in a row overlap this much
FURTHEST = 0.5  # of the picture: how far a rider moves from sample to sample
LOST_MS = 2000  # a rider unseen this long is let go

type Ref = tuple[str, int, int]  # segment, pts, ms: a frame as the journal names it


@dataclass
class Track:
    box: Box
    ms: int
    ref: Ref
    moved: float = 0.0  # the way it travels across the line: +1, -1, 0 unknown


@dataclass
class Crossing:
    """A rider's front changed side of the line between two frames."""

    before: Ref
    after: Ref
    box_before: Box
    box_after: Box


@dataclass
class Tracker:
    line: Line
    tracks: list[Track] = field(default_factory=list)

    def feed(self, boxes: list[Box], ref: Ref) -> list[Crossing]:
        """The riders of one sample; the crossings since the sample before."""
        ms = ref[2]
        self.tracks = [t for t in self.tracks if ms - t.ms <= LOST_MS]
        pairs = sorted(
            (distance(t.box, b), ti, bi)
            for ti, t in enumerate(self.tracks)
            for bi, b in enumerate(boxes)
        )
        taken_tracks: set[int] = set()
        taken_boxes: set[int] = set()
        crossings = []
        for apart, ti, bi in pairs:
            if apart > FURTHEST or ti in taken_tracks or bi in taken_boxes:
                continue
            taken_tracks.add(ti)
            taken_boxes.add(bi)
            found = self._follow(self.tracks[ti], boxes[bi], ref)
            if found is not None:
                crossings.append(found)
        for bi, box in enumerate(boxes):
            if bi not in taken_boxes:
                self.tracks.append(Track(box, ms, ref))
        return crossings

    def _follow(self, track: Track, box: Box, ref: Ref) -> Crossing | None:
        """The track at its new box; a crossing when its front, measured the way
        it travels, changed side of the line since the box before."""
        travel = side(self.line, centre(box)) - side(self.line, centre(track.box))
        if travel:
            track.moved = 1.0 if travel > 0 else -1.0
        earlier, earlier_ref = track.box, track.ref
        track.box, track.ms, track.ref = box, ref[2], ref
        if not track.moved:
            return None
        before = side(self.line, front(earlier, self.line, track.moved))
        after = side(self.line, front(box, self.line, track.moved))
        if before * after > 0 or before == after:
            return None
        return Crossing(earlier_ref, ref, earlier, box)


def centre(box: Box) -> Point:
    return (box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2


def front(box: Box, line: Line, moved: float) -> Point:
    """The middle of the box's edge that leads across ``line`` the way it moves."""
    (xa, ya), (xb, yb) = line
    way = (-(yb - ya) * moved, (xb - xa) * moved)  # across the line, as it travels
    x = box.x2 if way[0] > 0 else box.x1 if way[0] < 0 else (box.x1 + box.x2) / 2
    y = box.y2 if way[1] > 0 else box.y1 if way[1] < 0 else (box.y1 + box.y2) / 2
    return x, y


def refine(
    found: Crossing,
    frames: list[tuple[Any, Ref]],
    riders: Callable[[Any], list[Box]],
    line: Line,
) -> dict[str, Any] | None:
    """The crossing's moment from the frames between its two samples: the rider
    looked for again on each, the two frames around the line interpolated."""
    travel = side(line, centre(found.box_after)) - side(line, centre(found.box_before))
    moved = 1.0 if travel > 0 else -1.0
    seen: list[tuple[Ref, Point]] = [
        (found.before, front(found.box_before, line, moved))
    ]
    last = found.box_before
    for frame, ref in frames:
        if not found.before[2] < ref[2] < found.after[2]:
            continue
        near = max(riders(frame), key=lambda b: overlap(b, last), default=None)
        if near is not None and overlap(near, last) >= LEAST_OVERLAP:
            seen.append((ref, front(near, line, moved)))
            last = near
    seen.append((found.after, front(found.box_after, line, moved)))
    for (ref_a, a), (ref_b, b) in itertools.pairwise(seen):
        fraction = crossing(line, a, b)
        if fraction is not None:
            return {
                "ms": between(ref_a[2], ref_b[2], fraction),
                "frames": [list(ref_a), list(ref_b)],
                "fraction": round(fraction, 4),
            }
    return None


def distance(a: Box, b: Box) -> float:
    """How far apart two boxes' centres are, in the picture's 0-1 coordinates."""
    (ax, ay), (bx, by) = centre(a), centre(b)
    return float(np.hypot(ax - bx, ay - by))


def overlap(a: Box, b: Box) -> float:
    """How much two boxes overlap, as the detector measures it."""
    return iou(np.array([a.x1, a.y1, a.x2, a.y2]), np.array([b.x1, b.y1, b.x2, b.y2]))
