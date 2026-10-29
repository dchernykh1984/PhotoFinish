"""Suggested crossings as the window reads them, and the referee's decisions."""

from __future__ import annotations

import json
from pathlib import Path

from app.analysis.suggestions import Suggestions


def test_suggestions_are_read_as_appended_and_decisions_kept(tmp_path: Path) -> None:
    found = Suggestions(tmp_path)
    assert not found.refresh()
    path = tmp_path / "suggestions.jsonl"
    path.write_text(
        json.dumps({"id": "cam1-1000", "ms": 1000}) + "\n" + '{"id": "cam1-2'
    )
    assert found.refresh()
    assert [s["id"] for s in found.pending()] == ["cam1-1000"]
    with path.open("a") as f:
        f.write('000", "ms": 2000}\n[1]\nnot json\n')
    assert found.refresh()
    assert [s["id"] for s in found.pending()] == ["cam1-1000", "cam1-2000"]
    found.decide("cam1-1000", "dismissed")
    assert [s["id"] for s in found.pending()] == ["cam1-2000"]
    again = Suggestions(tmp_path)
    again.refresh()
    assert [s["id"] for s in again.pending()] == ["cam1-2000"]
    assert not again.refresh()


def test_a_crossing_suggested_twice_is_offered_once(tmp_path: Path) -> None:
    """The analyser killed between a segment's suggestions and its activity line
    analyses the segment again on restart."""
    line = json.dumps({"id": "cam1-1000", "ms": 1000}) + "\n"
    (tmp_path / "suggestions.jsonl").write_text(line + line)
    found = Suggestions(tmp_path)
    found.refresh()
    assert [s["id"] for s in found.pending()] == ["cam1-1000"]
