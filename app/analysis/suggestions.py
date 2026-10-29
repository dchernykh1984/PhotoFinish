"""A camera's suggested crossings, as its analyser appended them (002 US2), less
those the referee accepted or dismissed: those decisions are kept beside them in
``suggestions.done.jsonl``, so a restart does not offer them again. Both files are
read from where the last read stopped."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.analysis.analyzer import SUGGESTIONS
from app.files import Appended, append

DONE = "suggestions.done.jsonl"


class Suggestions:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.found: list[dict[str, Any]] = []
        self.done: set[str] = set()
        self._found = Appended(folder / SUGGESTIONS)
        self._decided = Appended(folder / DONE)

    def refresh(self) -> bool:
        """Suggestions and decisions written since; True when there were any."""
        found = _entries(self._found.new_lines())
        decided = _entries(self._decided.new_lines())
        self.found += found
        self.done |= {str(entry.get("id")) for entry in decided}
        return bool(found or decided)

    def pending(self) -> list[dict[str, Any]]:
        return [s for s in self.found if s.get("id") not in self.done]

    def decide(self, name: str, how: str) -> None:
        """``accepted`` or ``dismissed``: the suggestion is not offered again -- in
        this session even when the decision cannot be kept on disk, which raises."""
        self.done.add(name)
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
