"""The finish line and the caliper reading (research section 8).

A finish line is two points of the picture in 0-1 coordinates. A point of the rider
clicked on two frames lies some way before the line on one and past it on the
other; the moment it crossed is where the line falls between them, assuming a
steady speed from one frame to the other. Points on one side give nothing:
interpolating, never extrapolating, keeps a mistaken click from inventing a time.
The ratio of the two distances is the same in 0-1 coordinates as in pixels,
whatever the picture's proportions, so no size is needed.
"""

from __future__ import annotations

type Point = tuple[float, float]
type Line = tuple[Point, Point]

CENTRE: Line = ((0.5, 0.0), (0.5, 1.0))  # a camera's finish line until one is drawn


def points(drawn: object) -> Line | None:
    """Two different points within the picture, as the session keeps a finish line
    or a zone's corners; None for anything else."""
    if not (isinstance(drawn, list | tuple) and len(drawn) == 2):
        return None
    try:
        (xa, ya), (xb, yb) = ((float(x), float(y)) for x, y in drawn)
    except TypeError, ValueError:
        return None
    if not all(0 <= v <= 1 for v in (xa, ya, xb, yb)) or (xa, ya) == (xb, yb):
        return None
    return (xa, ya), (xb, yb)


def finish_line(drawn: object) -> Line:
    """A camera's finish line as the session keeps it, or the centre line."""
    return points(drawn) or CENTRE


def crossing(line: Line, first: Point, second: Point) -> float | None:
    """Where between the two frames the point crossed ``line``: 0 at the first frame,
    1 at the second; None when both points lie on one side of it."""
    a, b = side(line, first), side(line, second)
    if a * b > 0 or a == b:
        return None
    return a / (a - b)


def between(first_ms: int, second_ms: int, fraction: float) -> int:
    """The moment ``fraction`` of the way from one frame's moment to the next."""
    return round(first_ms + fraction * (second_ms - first_ms))


def side(line: Line, point: Point) -> float:
    """How far, and on which side, ``point`` lies from ``line`` (a cross product)."""
    (x1, y1), (x2, y2) = line
    return (x2 - x1) * (point[1] - y1) - (y2 - y1) * (point[0] - x1)
