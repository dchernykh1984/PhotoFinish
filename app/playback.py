"""Playing a recording at its own speed: which frame is due by the clock.

Qt-free, so the coverage gate measures it; the window's timer only asks.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

SKIP_MS = 1000  # no frame for longer than this: a gap playing jumps over


class Frames(Protocol):
    """A camera's recorded frames, by time: a VideoIndex or a FileIndex."""

    ms: np.ndarray

    def __len__(self) -> int: ...


type Start = tuple[float, int]  # the clock and the video's moment playing went on from


def play_on(
    frames: Frames, started: Start, now: float, offset: int
) -> tuple[int | None, Start]:
    """The place of the frame due at clock ``now`` -- the last one at or before the
    moment due -- and the start to go on from; ``offset`` is the camera's, added to
    its frames' times. In a gap longer than SKIP_MS (a recorder restarted, a camera
    that stalled) playing goes on from the first frame after it, rather than holding
    one frame for the gap's length. None once the newest frame is passed: playing on
    is Live."""
    clock, moment = started
    due = moment + round((now - clock) * 1000) - offset  # on the camera's times
    if not len(frames) or due >= int(frames.ms[-1]):
        return None, started
    after = int(np.searchsorted(frames.ms, due, side="right"))
    place = max(after - 1, 0)
    if due - int(frames.ms[place]) > SKIP_MS:
        return after, (now, int(frames.ms[after]) + offset)
    return place, started
