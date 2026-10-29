"""A camera's stretches with a rider in view, read from its analyser's files."""

from __future__ import annotations

import json
from pathlib import Path

from app.analysis.activity import Activity


def write(folder: Path, name: str, stretches: list[list[int]]) -> None:
    path = folder / f"{name}.activity.json"
    path.write_text(json.dumps({"version": 1, "stretches": stretches}))


def test_pieces_of_a_stretch_across_segments_are_one(tmp_path: Path) -> None:
    activity = Activity(tmp_path)
    assert not activity.refresh()
    write(tmp_path, "a", [[1000, 1900]])
    write(tmp_path, "b", [[2400, 2600], [9000, 9500]])
    (tmp_path / "c.activity.json").write_text("{half")
    assert activity.refresh()
    assert activity.stretches == [(1000, 2600), (9000, 9500)]
    (tmp_path / "c.activity.json").write_text(
        json.dumps({"stretches": [[20000, 20100]]})
    )
    assert activity.refresh()
    assert activity.stretches[-1] == (20000, 20100)
    assert not activity.refresh()


def test_next_and_previous_move_between_stretch_starts(tmp_path: Path) -> None:
    activity = Activity(tmp_path)
    write(tmp_path, "a", [[1000, 1500], [5000, 5500], [9000, 9500]])
    activity.refresh()
    assert activity.next_after(0) == 1000
    assert activity.next_after(1000) == 5000  # from a stretch's start: the next one
    assert activity.next_after(9100) is None
    assert activity.previous_before(5000) == 1000
    assert activity.previous_before(5200) == 1000  # just past a start: the one before
    assert activity.previous_before(6000) == 5000
    assert activity.previous_before(1000) is None


def test_how_far_the_analyser_got(tmp_path: Path) -> None:
    activity = Activity(tmp_path)
    activity.refresh()
    assert activity.progress is None
    (tmp_path / "analyzer.json").write_text(json.dumps({"done_ms": 1234}))
    activity.refresh()
    assert activity.progress == {"done_ms": 1234}
    (tmp_path / "analyzer.json").write_text("[1]")
    activity.refresh()
    assert activity.progress is None
