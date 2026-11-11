"""A camera's suggested crossings, as its analyser appended them (002 US2), less
those the referee accepted or dismissed: those decisions are kept beside them in
``suggestions.done.jsonl``, so a restart does not offer them again. Both files are
read from where the last read stopped."""

from __future__ import annotations

import bisect
import json
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.analysis.analyzer import SUGGESTIONS
from app.files import Appended, append

DONE = "suggestions.done.jsonl"
GATHER_MS = 300  # suggestions of several cameras this close: one crossing (006)

type Seen = tuple[int, str, dict[str, Any]]  # its moment on the timeline, camera, it


class Suggestions:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.found: list[dict[str, Any]] = []
        self.done: dict[str, str] = {}  # each decided: accepted or dismissed
        self._ids: set[str] = set()  # those found: a segment analysed twice adds none
        self._found = Appended(folder / SUGGESTIONS)
        self._decided = Appended(folder / DONE)

    def refresh(self) -> bool:
        """Suggestions and decisions written since; True when there were any."""
        found = []
        for entry in _entries(self._found.new_lines()):
            if str(entry.get("id")) not in self._ids:
                self._ids.add(str(entry.get("id")))
                found.append(entry)
        decided = _entries(self._decided.new_lines())
        self.found += found
        # Any line decides its suggestion, as before decisions said how: one
        # without the word, written by hand, still keeps it from coming back.
        self.done |= {
            str(e.get("id")): str(e.get("done") or "decided") for e in decided
        }
        return bool(found or decided)

    def decide(self, name: str, how: str) -> None:
        """``accepted`` or ``dismissed``: the suggestion is not offered again -- in
        this session even when the decision cannot be kept on disk, which raises."""
        self.done[name] = how
        line = json.dumps({"id": name, "done": how}) + "\n"
        append(self.folder / DONE, line.encode("ascii"))


def _entries(lines: list[str]) -> list[dict[str, Any]]:
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


@dataclass
class Gathered:
    """One crossing as the cameras saw it (006, FR-003): each camera's suggestion
    and the number read."""

    seen: list[Seen]
    number: str

    @property
    def kept(self) -> Seen:
        """The suggestion at the median -- for an even count, the earlier of the
        two in the middle: its moment is the one written, and its camera's frames,
        which the journal names, give that very moment."""
        ordered = sorted(self.seen, key=lambda one: one[0])
        return ordered[(len(ordered) - 1) // 2]

    @property
    def moment(self) -> int:
        return self.kept[0]


def gathered(found: list[Seen], within_ms: int = GATHER_MS) -> list[Gathered]:
    """The suggestions as crossings: each joins, of the crossings begun within
    ``within_ms`` before it that no suggestion of its camera is in yet, nor a number
    read apart from its own, nor one whose camera has another suggestion nearer to
    it, the one nearest its moment -- one camera's never gather, so riders abreast
    stay apart, and a rider one camera missed is not paired with the rider before,
    whether it comes first or a moment before; numbers read apart are two riders."""
    by_camera: dict[str, list[int]] = {}
    for seen in found:
        by_camera.setdefault(seen[1], []).append(seen[0])
    for moments in by_camera.values():
        moments.sort()
    crossings: list[list[Seen]] = []
    for one in sorted(found, key=lambda seen: seen[0]):
        open_ = []
        for c in reversed(crossings):  # begun in order: the latest are the open ones
            if one[0] - c[0][0] > within_ms:
                break  # and every one before it began earlier still
            mine = one[1] in {s[1] for s in c}
            if not mine and _agrees(one, c) and _nearest(one, c, by_camera):
                open_.append(c)
        open_.reverse()  # in the order begun: between equals, the earlier is taken
        nearest = min(
            open_,
            key=lambda c: abs(one[0] - statistics.median(s[0] for s in c)),
            default=None,
        )
        if nearest is None:
            crossings.append([one])
        else:
            nearest.append(one)
    return [Gathered(c, _number(c)) for c in crossings]


def _nearest(one: Seen, crossing: list[Seen], by_camera: dict[str, list[int]]) -> bool:
    """Each of the crossing's suggestions is its camera's nearest to ``one``: a
    camera with one nearer saw ``one``'s rider there."""
    for moment, camera, _ in crossing:
        moments = by_camera[camera]
        at = bisect.bisect_left(moments, one[0])
        best = min(abs(m - one[0]) for m in moments[max(at - 1, 0) : at + 1])
        if abs(moment - one[0]) > best:
            return False
    return True


def _agrees(one: Seen, crossing: list[Seen]) -> bool:
    """No number read on the suggestion, or none on the crossing but its own."""
    number = one[2].get("number")
    return not number or all(s[2].get("number") in (None, "", number) for s in crossing)


def remaining(
    crossing: Gathered, decided: Callable[[str, dict[str, Any]], str | None]
) -> tuple[Gathered | None, str]:
    """A crossing's suggestions still to decide, and how one of the others was
    decided (``decided`` by camera and suggestion): a camera's suggestion arriving
    after its crossing was decided is offered still -- it may be another rider --
    with that said, never decided for the referee (006)."""
    left, how = [], ""
    for one in crossing.seen:
        verdict = decided(one[1], one[2])
        if verdict:
            how = how or verdict
        else:
            left.append(one)
    return (Gathered(left, _number(left)) if left else None), how


def _number(crossing: list[Seen]) -> str:
    """The number its cameras read -- none apart, as they gather -- "" when none
    was read."""
    return next((str(s[2]["number"]) for s in crossing if s[2].get("number")), "")
