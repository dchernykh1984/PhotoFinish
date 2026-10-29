"""The caliper: the moment a point crossed the finish line between two frames."""

from __future__ import annotations

import pytest

from app.interpolation import CENTRE, between, crossing, finish_line


def test_three_units_before_and_one_past_is_three_quarters() -> None:
    """US5's independent test, in numbers: a vertical line at x = 10."""
    line = ((10.0, 0.0), (10.0, 1.0))
    assert crossing(line, (7.0, 0.5), (11.0, 0.5)) == pytest.approx(0.75)
    assert crossing(line, (11.0, 0.5), (7.0, 0.3)) == pytest.approx(0.25)
    assert between(1000, 1016, 0.75) == 1012


def test_points_on_one_side_give_nothing() -> None:
    assert crossing(CENTRE, (0.2, 0.5), (0.4, 0.9)) is None
    assert crossing(CENTRE, (0.5, 0.1), (0.5, 0.9)) is None  # both on it: no telling
    assert crossing(CENTRE, (0.5, 0.5), (0.7, 0.5)) == 0.0
    assert crossing(CENTRE, (0.3, 0.5), (0.5, 0.5)) == 1.0


def test_a_slanted_line_reads_the_same_in_any_proportions() -> None:
    line = ((0.2, 0.0), (0.6, 1.0))
    a, b = (0.1, 0.5), (0.7, 0.4)
    stretched = ((0.2 * 16, 0.0), (0.6 * 16, 9.0))
    fraction = crossing(line, a, b)
    assert fraction is not None
    assert crossing(stretched, (a[0] * 16, a[1] * 9), (b[0] * 16, b[1] * 9)) == (
        pytest.approx(fraction)
    )


@pytest.mark.parametrize(
    ("drawn", "line"),
    [
        (None, CENTRE),
        ([[0.1, 0], [0.9, 1]], ((0.1, 0.0), (0.9, 1.0))),
        ([[0.1, 0.1], [0.1, 0.1]], CENTRE),
        ([[0.1, "x"], [0.9, 1]], CENTRE),
        ([1, 2], CENTRE),
        ([[0.1, 0], [1.5, 1]], CENTRE),  # outside the picture
        ([[float("nan"), 0], [0.9, 1]], CENTRE),
    ],
)
def test_a_camera_line_as_the_session_keeps_it(drawn: object, line: object) -> None:
    assert finish_line(drawn) == line
