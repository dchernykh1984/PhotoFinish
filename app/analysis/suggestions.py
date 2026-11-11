"""A camera's suggested crossings, as its analyser appended them (002 US2), less
those the referee accepted or dismissed: those decisions are kept beside them in
``suggestions.done.jsonl``, so a restart does not offer them again. Both files are
read from where the last read stopped."""

from __future__ import annotations

import json
import statistics
from collections import Counter
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

    def pending(self) -> list[dict[str, Any]]:
        return [s for s in self.found if s.get("id") not in self.done]

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
    and the number most read."""

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
    ``within_ms`` before it that no suggestion of its camera is in yet, the one
    nearest its moment -- one camera's never gather, so riders abreast stay apart,
    and a rider one camera missed is not paired with the rider before."""
    crossings: list[list[Seen]] = []
    for one in sorted(found, key=lambda seen: seen[0]):
        open_ = []
        for c in reversed(crossings):  # begun in order: the latest are the open ones
            if one[0] - c[0][0] > within_ms:
                break  # and every one before it began earlier still
            if one[1] not in {s[1] for s in c}:
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
    """The number most of the cameras read, the surer reading between equals; ""
    when none was read."""
    read = [
        (str(s[2]["number"]), float(s[2].get("number_sure", 0)))
        for s in crossing
        if s[2].get("number")
    ]
    if not read:
        return ""
    times = Counter(number for number, _ in read)
    return max(read, key=lambda r: (times[r[0]], r[1]))[0]
