"""A camera's suggested crossings, as its analyser appended them (002 US2), less
those the referee accepted or dismissed: those decisions are kept beside them in
``suggestions.done.jsonl``, so a restart does not offer them again."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.analysis.analyzer import SUGGESTIONS

DONE = "suggestions.done.jsonl"


class Suggestions:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.found: list[dict[str, Any]] = []
        self.done: set[str] = set()
        self._read = 0  # bytes of the suggestions read
        self._done_read = 0  # bytes of the decisions read; none is no file

    def refresh(self) -> bool:
        """Suggestions and decisions written since; True when there were any."""
        news = self._read_suggestions()
        try:
            size = (self.folder / DONE).stat().st_size
        except OSError:
            size = 0
        if size != self._done_read:
            self._done_read, news = size, True
            decided = _lines(self.folder / DONE, 0)[0]
            self.done = {str(entry.get("id")) for entry in decided}
        return news

    def pending(self) -> list[dict[str, Any]]:
        return [s for s in self.found if s.get("id") not in self.done]

    def decide(self, name: str, how: str) -> None:
        """``accepted`` or ``dismissed``: the suggestion is not offered again."""
        with (self.folder / DONE).open("a", encoding="ascii") as f:
            f.write(json.dumps({"id": name, "done": how}) + "\n")
        self.done.add(name)

    def _read_suggestions(self) -> bool:
        found, self._read = _lines(self.folder / SUGGESTIONS, self._read)
        self.found += found
        return bool(found)


def _lines(path: Path, start: int) -> tuple[list[dict[str, Any]], int]:
    """The complete JSON lines of ``path`` from byte ``start``; where they end."""
    try:
        with path.open("rb") as f:
            f.seek(start)
            data = f.read()
    except OSError:
        return [], start
    complete = data[: data.rfind(b"\n") + 1]
    entries = []
    for line in complete.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries, start + len(complete)
