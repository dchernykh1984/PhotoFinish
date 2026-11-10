"""Playing a recording at its own speed: which frame is due by the clock.

Qt-free, so the coverage gate measures it; the window's timer only asks.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class Frames(Protocol):
    """A camera's recorded frames, by time: a VideoIndex or a FileIndex."""

    ms: np.ndarray

    def __len__(self) -> int: ...

    def nearest(self, ms: int, within: int | None = None) -> int | None: ...


def frame_due(
    frames: Frames, started: tuple[float, int], now: float, offset: int
) -> int | None:
    """The place of the frame due at clock ``now``, playing having started at clock
    ``started[0]`` on the video's moment ``started[1]``; ``offset`` is the camera's,
    added to its frames' times. None once the newest frame is passed: playing on is
    Live."""
    clock, moment = started
    due = moment + round((now - clock) * 1000)
    if not len(frames) or due >= int(frames.ms[-1]) + offset:
        return None
    return frames.nearest(due - offset)
