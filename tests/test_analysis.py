"""Finding riders: the settings and the zone around the finish line."""

from __future__ import annotations

from typing import Any

import pytest

from app import analysis, cameras


def test_analysis_is_off_until_turned_on() -> None:
    assert analysis.settings({}) == {"on": False, "model": ""}
    assert analysis.settings({"analysis": "on"}) == {"on": False, "model": ""}
    chosen = {"analysis": {"on": 1, "model": "yolox_s.onnx"}}
    assert analysis.settings(chosen) == {"on": True, "model": "yolox_s.onnx"}


def test_without_a_zone_drawn_it_is_a_band_around_the_line() -> None:
    assert analysis.zone({}) == ((0.35, 0.0), (0.65, 1.0))
    slanted = {"finish_line": [[0.1, 0.3], [0.2, 0.9]]}
    assert analysis.zone(slanted) == (
        (0.0, pytest.approx(0.15)),
        (pytest.approx(0.35), 1.0),
    )


def test_a_drawn_zone_is_its_two_corners_whichever_were_clicked_first() -> None:
    assert analysis.zone({"zone": [[0.7, 0.9], [0.3, 0.2]]}) == ((0.3, 0.2), (0.7, 0.9))


@pytest.mark.parametrize(
    "drawn",
    [
        None,
        [[0.1, 0.1], [0.1, 0.9]],
        [[0, 0], [2, 1]],
        [[0, "x"], [1, 1]],
        [1, 2],
        "all",
    ],
)
def test_a_zone_that_spans_nothing_is_not_one(drawn: Any) -> None:
    assert not analysis.valid_zone(drawn)
    assert analysis.zone({"zone": drawn}) == ((0.35, 0.0), (0.65, 1.0))
    if drawn is not None:
        found = cameras.problems({"connection": "test", "zone": drawn})
        assert found == ["the zone must be two corners of a part of the picture"]


def test_lines_appended_are_read_once_each(tmp_path) -> None:
    from app.files import Appended

    path = tmp_path / "list.txt"
    appended = Appended(path)
    assert appended.new_lines() == []
    path.write_text("a\nb\n\nc")
    assert appended.new_lines() == ["a", "b"]
    with path.open("a") as f:
        f.write("d\n")
    assert appended.new_lines() == ["cd"]
    path.write_text("x\n")  # shorter: replaced, read from its start
    assert appended.new_lines() == ["x"]
