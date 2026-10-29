"""Finding riders in the video: experimental, off by default (specs/002-video-analysis).

An analyser process per camera indexes the stretches where a rider is in view, from
motion that travels across a zone around the finish line, or from a detector model
the referee installed. It only helps the referee find the moments to look at;
timing stays by hand.
"""

from __future__ import annotations

from typing import Any

from app.interpolation import Point, finish_line, points

type Zone = tuple[Point, Point]  # two opposite corners in 0-1 picture coordinates

ZONE_MARGIN = 0.15  # the zone around a finish line no one drew it for


def settings(session: dict[str, Any]) -> dict[str, Any]:
    """The analysis settings: on, and the model file (empty: motion only)."""
    saved = session.get("analysis")
    saved = saved if isinstance(saved, dict) else {}
    return {"on": bool(saved.get("on", False)), "model": str(saved.get("model") or "")}


def zone(camera: dict[str, Any]) -> Zone:
    """Where motion is looked for: as the referee drew it, or a band around the
    camera's finish line."""
    drawn = _corners(camera.get("zone"))
    if drawn is not None:
        return drawn
    (x1, y1), (x2, y2) = finish_line(camera.get("finish_line"))
    return (
        (max(min(x1, x2) - ZONE_MARGIN, 0.0), max(min(y1, y2) - ZONE_MARGIN, 0.0)),
        (min(max(x1, x2) + ZONE_MARGIN, 1.0), min(max(y1, y2) + ZONE_MARGIN, 1.0)),
    )


def valid_zone(drawn: object) -> bool:
    return _corners(drawn) is not None


def _corners(drawn: object) -> Zone | None:
    """Two corners within the picture that span an area, the top-left first."""
    found = points(drawn)
    if found is None:
        return None
    (xa, ya), (xb, yb) = found
    if xa == xb or ya == yb:
        return None
    return (min(xa, xb), min(ya, yb)), (max(xa, xb), max(ya, yb))
