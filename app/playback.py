"""Playing a recording at its own speed: which frame is due by the clock.

Qt-free, so the coverage gate measures it; the window's timer only asks.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

SKIP_MS = 1000  # no frame for longer than this: a gap playing jumps over
SLOWEST, FASTEST = 1 / 16, 16.0  # the speeds offered, halving and doubling (012)


class Frames(Protocol):
    """A camera's recorded frames, by time: a VideoIndex or a FileIndex."""

    ms: np.ndarray

    def __len__(self) -> int: ...


type Start = tuple[float, int]  # the clock and the video's moment playing went on from


def speed_name(speed: float) -> str:
    """A speed as its button names it: x2, x0.5, x0.25, and x1/8 below, not x0.125."""
    return f"x{speed:g}" if speed >= 0.25 else f"x1/{round(1 / speed)}"


def moment_due(started: Start, now: float, rate: float) -> int:
    """The video's moment due at clock ``now``: where playing went on from, and the
    time since at ``rate``, below 0 backwards."""
    clock, moment = started
    return moment + round((now - clock) * 1000 * rate)


def play_on(
    frames: Frames, started: Start, now: float, offset: int, rate: float = 1.0
) -> tuple[int | None, Start]:
    """The place of the frame due at clock ``now`` -- the last one at or before the
    moment due -- and the start to go on from; ``offset`` is the camera's, added to
    its frames' times, ``rate`` the speed, below 0 backwards (specs/012). In a gap
    longer than SKIP_MS (a recorder restarted, a camera that stalled, one that
    started later) playing goes on from the first frame after it, rather than
    holding one frame for the gap's length. None once the newest frame is passed:
    playing on is Live -- or, backwards, once the first is: playing ends."""
    due = moment_due(started, now, rate) - offset  # the camera's times
    if rate < 0:
        return _back(frames, started, now, offset, due)
    if not len(frames) or due >= int(frames.ms[-1]):
        return None, started
    after = int(np.searchsorted(frames.ms, due, side="right"))
    if after == 0:  # before the camera's first frame: the same as a gap
        if int(frames.ms[0]) - due > SKIP_MS:
            return 0, (now, int(frames.ms[0]) + offset)
        return 0, started
    if due - int(frames.ms[after - 1]) > SKIP_MS:
        return after, (now, int(frames.ms[after]) + offset)
    return after - 1, started


def _back(
    frames: Frames, started: Start, now: float, offset: int, due: int
) -> tuple[int | None, Start]:
    """Backwards, the mirror of forwards: the first frame at or after the moment
    ``due``; a gap longer than SKIP_MS before it jumped over to the frame on its far
    side; None at or before the first frame."""
    if not len(frames) or due <= int(frames.ms[0]):
        return None, started
    before = int(np.searchsorted(frames.ms, due, side="left"))
    if before == len(frames):  # after the newest frame: as forwards before the first
        if due - int(frames.ms[-1]) > SKIP_MS:
            return before - 1, (now, int(frames.ms[-1]) + offset)
        return before - 1, started
    if int(frames.ms[before]) - due > SKIP_MS:
        return before - 1, (now, int(frames.ms[before - 1]) + offset)
    return before, started
