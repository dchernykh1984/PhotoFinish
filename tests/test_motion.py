"""Finding riders by motion: passes counted, swaying leaves not (002 SC-001)."""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.motion import Motion, Stretches
from app.interpolation import CENTRE
from app.recorder.testcam import render, rider_front

START = 1_761_716_120_000  # a multiple of 10 s: passes start 2 s after it
ZONE = ((0.35, 0.25), (0.65, 0.9))  # around the line, clear of the clock and strip


def grey(ms: int, scene: str) -> np.ndarray:
    """The test camera's frame as the analyser looks at it: grey, 160 wide."""
    rgb = render(ms, 640, 360, scene).astype(np.float32)
    return rgb.mean(axis=2).reshape(90, 4, 160, 4).mean(axis=(1, 3)).astype(np.uint8)


def index(scene: str, seconds: int = 30) -> list[list[int]]:
    motion, stretches = Motion(ZONE, CENTRE), Stretches()
    for k in range(seconds * 5):
        ms = START + k * 200
        stretches.add(ms, motion.feed(grey(ms, scene), ms))
    return stretches.found


def test_three_passes_are_three_stretches_while_the_rider_is_in_the_zone() -> None:
    found = index("passes")
    assert len(found) == 3
    for n, (start, end) in enumerate(found):
        for ms in (start, end):
            front = rider_front(ms, 640)
            assert front is not None, (n, ms - START)
            assert 0.35 * 640 <= front <= 0.65 * 640 + 640 // 8


def test_leaves_swaying_in_the_zone_mark_nothing() -> None:
    assert index("sway") == []


def test_motion_that_does_not_travel_across_the_line_marks_nothing() -> None:
    """A rider moving along the line, top to bottom, crosses no line."""
    motion, stretches = Motion(ZONE, CENTRE), Stretches()
    base = grey(START, "clock")
    for k in range(20):
        frame = base.copy()
        frame[20 + k * 3 : 30 + k * 3, 70:90] = 0  # down the middle of the zone
        stretches.add(START + k * 200, motion.feed(frame, START + k * 200))
    assert stretches.found == []


def test_a_new_size_or_tiny_motion_starts_over() -> None:
    motion = Motion(ZONE, CENTRE)
    assert motion.feed(np.zeros((90, 160), np.uint8), START) is None
    assert motion.feed(np.zeros((45, 80), np.uint8), START + 200) is None
    speck = np.zeros((45, 80), np.uint8)
    speck[20, 40] = 255
    assert motion.feed(speck, START + 400) is None


@pytest.mark.parametrize(
    ("moments", "found"),
    [
        ([(1000, 900), (1200, 900), (5000, 4800)], [[900, 1200], [4800, 5000]]),
        ([(1000, None), (1200, 1100)], [[1100, 1200]]),
        ([(1000, 900), (2500, 2100)], [[900, 1000], [2100, 2500]]),
        ([(1000, 900), (2000, 1900)], [[900, 2000]]),
    ],
)
def test_moments_gather_into_stretches(
    moments: list[tuple[int, int | None]], found: list[list[int]]
) -> None:
    stretches = Stretches()
    for ms, since in moments:
        stretches.add(ms, since)
    assert stretches.found == found
