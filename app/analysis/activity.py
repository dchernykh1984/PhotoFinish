"""A camera's stretches with a rider in view, as its analyser wrote them.

The window reads the lines the analyser appends to ``activity.jsonl``, each once,
joins the pieces of a stretch that crossed segments, and moves between stretches
with "Next rider" and "Previous rider". ``analyzer.json`` tells how far the
analyser has got.
"""

from __future__ import annotations

import bisect
import json
from pathlib import Path
from typing import Any

from app.analysis.analyzer import ACTIVITY
from app.files import Appended, read_json

JOIN_MS = 1000  # pieces this close are one stretch
_STEP_MS = 300  # "next" from inside a stretch's first moments is the one after


class Activity:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.stretches: list[tuple[int, int]] = []
        self.progress: dict[str, Any] | None = None
        self._pieces: list[tuple[int, int]] = []
        self._read: set[str] = set()  # segments read: a list read again adds none
        self._lines = Appended(folder / ACTIVITY)

    def refresh(self) -> bool:
        """Activity written since the last refresh read; True when there was any."""
        self.progress = read_json(self.folder / "analyzer.json")
        new = False
        for line in self._lines.new_lines():
            try:
                found = json.loads(line)
                name = str(found["segment"])
                pieces = [(int(a), int(b)) for a, b in found.get("stretches", [])]
            except ValueError, KeyError, TypeError:
                continue
            if name not in self._read:
                self._read.add(name)
                self._pieces += pieces
                new = True
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
