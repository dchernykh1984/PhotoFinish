"""Suggested crossings as the window reads them, and the referee's decisions."""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.analysis.suggestions import Suggestions, gathered, remaining


def test_suggestions_are_read_as_appended_and_decisions_kept(tmp_path: Path) -> None:
    found = Suggestions(tmp_path)
    assert not found.refresh()
    path = tmp_path / "suggestions.jsonl"
    path.write_text(
        json.dumps({"id": "cam1-1000", "ms": 1000}) + "\n" + '{"id": "cam1-2'
    )
    assert found.refresh()
    assert [s["id"] for s in found.found] == ["cam1-1000"]
    with path.open("a") as f:
        f.write('000", "ms": 2000}\n[1]\nnot json\n')
    assert found.refresh()
    assert [s["id"] for s in found.found] == ["cam1-1000", "cam1-2000"]
    found.decide("cam1-1000", "dismissed")
    assert found.done == {"cam1-1000": "dismissed"}
    again = Suggestions(tmp_path)
    again.refresh()
    assert [s["id"] for s in again.found] == ["cam1-1000", "cam1-2000"]
    assert again.done == {"cam1-1000": "dismissed"}
    assert not again.refresh()


def test_a_decision_without_its_word_still_decides(tmp_path: Path) -> None:
    lines = '{"id": "cam1-1000"}\n{"id": "cam1-2000", "done": ""}\n'
    (tmp_path / "suggestions.done.jsonl").write_text(lines)
    found = Suggestions(tmp_path)
    found.refresh()
    assert found.done == {"cam1-1000": "decided", "cam1-2000": "decided"}


def test_suggestions_that_read_numbers_apart_are_two_riders() -> None:
    """Each camera missed the other's rider: accepted together, one would be lost."""
    twelve = (10, "camB", {"id": "b", "number": "12", "number_sure": 0.95})
    unread = (100, "camC", {"id": "c"})
    thirty_four = (200, "camA", {"id": "a", "number": "34", "number_sure": 0.9})
    found = gathered([twelve, unread, thirty_four])
    assert [[s[2]["id"] for s in g.seen] for g in found] == [["b", "c"], ["a"]]
    assert [g.number for g in found] == ["12", "34"]
    assert gathered([]) == []


def test_a_crossing_suggested_twice_is_offered_once(tmp_path: Path) -> None:
    """The analyser killed between a segment's suggestions and its activity line
    analyses the segment again on restart."""
    line = json.dumps({"id": "cam1-1000", "ms": 1000}) + "\n"
    (tmp_path / "suggestions.jsonl").write_text(line + line)
    found = Suggestions(tmp_path)
    found.refresh()
    assert [s["id"] for s in found.found] == ["cam1-1000"]


def test_several_cameras_suggestions_of_one_crossing_are_one() -> None:
    """006 FR-003: at their median, with the number read."""
    side = (1_000, "cam1", {"id": "a", "number": "27", "number_sure": 0.9})
    front = (1_040, "cam2", {"id": "b"})  # not read there
    top = (1_020, "cam3", {"id": "c", "number": "27", "number_sure": 0.8})
    later = (1_400, "cam2", {"id": "d"})
    [one, other] = gathered([front, later, side, top])
    assert one.moment == 1_020
    assert {s[1] for s in one.seen} == {"cam1", "cam2", "cam3"}
    assert one.number == "27"
    assert one.kept[1] == "cam3"  # its moment is the median
    assert (other.moment, other.number, len(other.seen)) == (1_400, "", 1)


def test_one_camera_s_suggestions_never_gather_so_riders_abreast_stay_apart() -> None:
    first = (1_000, "cam1", {"id": "a"})
    second = (1_000, "cam1", {"id": "a-2"})
    seen = (1_010, "cam2", {"id": "b"})
    also = (1_012, "cam2", {"id": "b-2"})
    crossings = gathered([first, second, seen, also])
    assert [[s[2]["id"] for s in c.seen] for c in crossings] == [
        ["a", "b"],
        ["a-2", "b-2"],
    ]
    assert gathered([first, (1_301, "cam2", {"id": "far"})], within_ms=300)[0].seen == [
        first
    ]


def test_a_suggestion_joins_the_nearest_crossing_not_the_first() -> None:
    """A rider one camera missed is not paired with the rider before."""
    a1 = (0, "cam1", {"id": "a1"})
    b1 = (100, "cam1", {"id": "b1"})
    b2 = (110, "cam2", {"id": "b2", "number": "18", "number_sure": 0.99})
    first, second = gathered([a1, b1, b2])
    assert [s[2]["id"] for s in first.seen] == ["a1"]
    assert [s[2]["id"] for s in second.seen] == ["b1", "b2"]
    assert (first.number, second.number) == ("", "18")


def test_what_is_left_of_a_crossing_decided_in_part_is_offered_with_the_decision() -> (
    None
):
    side = (1_000, "cam1", {"id": "a", "number": "27", "number_sure": 0.9})
    front = (1_030, "cam2", {"id": "b", "number": "27", "number_sure": 0.85})
    [crossing] = gathered([side, front])
    decided = {"a": "accepted"}
    left, how = remaining(crossing, lambda camera, found: decided.get(found["id"]))
    assert left is not None
    assert ([s[2]["id"] for s in left.seen], left.number, how) == (
        ["b"],
        "27",
        "accepted",
    )
    decided["b"] = "dismissed"
    assert remaining(crossing, lambda camera, found: decided.get(found["id"])) == (
        None,
        "accepted",
    )
    assert remaining(crossing, lambda camera, found: None)[1] == ""


def test_a_day_of_suggestions_is_gathered_in_a_moment() -> None:
    """Every suggestion is gathered each time one comes: a race day's thousands
    look only at the crossings begun within the window, not all before them."""
    day = [
        (n * 1_000 + k, f"cam{k}", {"id": f"{n}-{k}"})
        for n in range(20_000)
        for k in (1, 2)
    ]
    started = time.perf_counter()
    crossings = gathered(day)
    assert time.perf_counter() - started < 3.0
    assert len(crossings) == 20_000
