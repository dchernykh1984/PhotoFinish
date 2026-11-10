"""Which frame playing shows, by the clock."""

from __future__ import annotations

import numpy as np

from app.playback import play_on


class Frames:
    """Frames 33 ms apart, as a 30 fps camera records them, and a gap if asked."""

    def __init__(self, count: int, first: int = 1000, gap_after: int = 0) -> None:
        self.ms = first + 33 * np.arange(count, dtype=np.int64)
        if gap_after:
            self.ms[gap_after:] += 600_000  # ten minutes without a frame

    def __len__(self) -> int:
        return len(self.ms)


def test_the_frame_due_follows_the_clock_from_where_playing_started() -> None:
    frames = Frames(70)
    start = (50.0, 1000 + 9 * 33)  # played from frame 9
    assert play_on(frames, start, 50.0, 0) == (9, start)
    assert play_on(frames, start, 50.33, 0) == (19, start)  # a third of a second on
    assert play_on(frames, start, 50.03, 0) == (9, start)  # frame 10 not due yet


def test_the_cameras_offset_is_added_to_its_frames_times() -> None:
    frames = Frames(70)
    offset = 500  # the camera's frames show 500 ms later on the video's time
    start = (0.0, 1000 + 9 * 33 + offset)
    assert play_on(frames, start, 0.33, offset) == (19, start)


def test_past_the_newest_frame_playing_is_live() -> None:
    frames = Frames(70)
    newest = 1000 + 69 * 33
    start = (0.0, newest - 100)
    assert play_on(frames, start, 0.05, 0) == (67, start)
    assert play_on(frames, start, 0.1, 0) == (None, start)
    assert play_on(frames, start, 0.1, 200) == (62, start)  # offset: not yet
    assert play_on(Frames(0), (0.0, 0), 1.0, 0) == (None, (0.0, 0))


def test_playing_jumps_over_a_gap_instead_of_holding_a_frame_through_it() -> None:
    frames = Frames(20, gap_after=10)  # frames 0-9, ten minutes, frames 10-19
    start = (0.0, 1000 + 5 * 33)
    assert play_on(frames, start, 0.9, 0) == (9, start)  # a second without: held
    after_gap = int(frames.ms[10])
    place, start = play_on(frames, start, 2.0, 0)
    assert (place, start) == (10, (2.0, after_gap))  # on from the frame after it
    assert play_on(frames, start, 2.033, 0) == (11, start)


def test_playing_from_before_the_cameras_first_frame_jumps_to_it() -> None:
    frames = Frames(10, first=300_000)  # a camera that started five minutes later
    place, start = play_on(frames, (0.0, 1000), 0.0, 0)
    assert (place, start) == (0, (0.0, 300_000))
    assert play_on(frames, start, 0.033, 0) == (1, start)
    near = (0.0, 300_000 - 500)  # half a second before it: held, not jumped
    assert play_on(frames, near, 0.0, 0) == (0, near)
