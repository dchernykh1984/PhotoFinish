"""A camera's stretches with a rider in view, as its analyser wrote them.

The window reads each segment's ``.activity.json`` once, joins the pieces of a
stretch that crossed segments, and moves between stretches with "Next rider" and
"Previous rider". ``analyzer.json`` tells how far the analyser has got.
"""

from __future__ import annotations

import bisect
import json
from pathlib import Path
from typing import Any

JOIN_MS = 1000  # pieces this close are one stretch
_STEP_MS = 300  # "next" from inside a stretch's first moments is the one after


class Activity:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.stretches: list[tuple[int, int]] = []
        self.progress: dict[str, Any] | None = None
        self._pieces: list[tuple[int, int]] = []
        self._read: set[str] = set()

    def refresh(self) -> bool:
        """Activity written since the last refresh read; True when there was any."""
        self.progress = _json(self.folder / "analyzer.json")
        new = [
            p for p in self.folder.glob("*.activity.json") if p.name not in self._read
        ]
        for path in new:
            found = _json(path)
            if found is None:
                continue  # half written: the next refresh
            self._read.add(path.name)
            self._pieces += [(int(a), int(b)) for a, b in found.get("stretches", [])]
        if not new:
            return False
        self.stretches = _joined(sorted(self._pieces))
        return True

    def next_after(self, ms: int) -> int | None:
        """The start of the first stretch after ``ms``."""
        starts = [start for start, _ in self.stretches]
        place = bisect.bisect_right(starts, ms + _STEP_MS)
        return starts[place] if place < len(starts) else None

    def previous_before(self, ms: int) -> int | None:
        """The start of the last stretch before ``ms``."""
        starts = [start for start, _ in self.stretches]
        place = bisect.bisect_left(starts, ms - _STEP_MS)
        return starts[place - 1] if place > 0 else None


def _joined(pieces: list[tuple[int, int]]) -> list[tuple[int, int]]:
    joined: list[tuple[int, int]] = []
    for start, end in pieces:
        if joined and start <= joined[-1][1] + JOIN_MS:
            joined[-1] = (joined[-1][0], max(joined[-1][1], end))
        else:
            joined.append((start, end))
    return joined


def _json(path: Path) -> dict[str, Any] | None:
    try:
        found = json.loads(path.read_text(encoding="ascii"))
    except OSError, ValueError:
        return None
    return found if isinstance(found, dict) else None
