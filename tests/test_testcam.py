"""The test camera: frames that carry their own time."""

from __future__ import annotations

import numpy as np
import pytest

from app.recorder.testcam import TestCamera, read_time, render

MOMENT = 1_761_716_129_587


def test_a_frame_carries_its_moment() -> None:
    for ms in (0, 1, MOMENT, 2**44 - 1):
        assert read_time(render(ms, 640, 360)) == ms


def test_the_scenes_move() -> None:
    def middle(ms: int, scene: str) -> np.ndarray:
        return render(ms, 640, 360, scene)[100:250]

    assert middle(5000, "flash").min() == 255
    assert middle(5100, "flash").max() < 255
    bar = middle(MOMENT, "bar")[0, :, 0]
    later = middle(MOMENT + 100, "bar")[0, :, 0]
    assert int(np.argmax(later == 255)) - int(np.argmax(bar == 255)) == 64
    assert not np.array_equal(middle(0, "sway"), middle(500, "sway"))
    with pytest.raises(ValueError, match="scene"):
        TestCamera(scene="rain")


class FakeClock:
    def __init__(self) -> None:
        self.ms = MOMENT
        self.slept: list[float] = []

    def __call__(self) -> int:
        return self.ms

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.ms += round(seconds * 1000)


def test_frames_come_at_their_moments_and_late_ones_are_dropped() -> None:
    clock = FakeClock()
    frames = TestCamera(fps=30, width=640, height=360, clock=clock, sleep=clock.sleep)
    taken = frames.frames()
    moments = [next(taken)[1] for _ in range(4)]
    assert moments == [MOMENT, MOMENT + 33, MOMENT + 67, MOMENT + 100]
    assert clock.slept == [0.033, 0.034, 0.033]
    clock.ms += 200  # the last frame took long: the frames of that time are gone
    image, ms = next(taken)
    assert ms == MOMENT + 300
    assert read_time(image) == ms
