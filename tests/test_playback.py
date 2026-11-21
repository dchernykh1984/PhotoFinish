"""Which frame playing shows, by the clock."""

from __future__ import annotations

import numpy as np

from app.playback import FASTEST, SLOWEST, moment_due, play_on, speed_name


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


def test_a_rate_plays_faster_or_slower_from_where_playing_started() -> None:
    frames = Frames(70)
    start = (50.0, 1000 + 9 * 33)
    assert play_on(frames, start, 50.33, 0, rate=2.0) == (29, start)  # 660 ms on
    assert play_on(frames, start, 50.33, 0, rate=0.25) == (11, start)  # 82 ms on
    assert play_on(frames, start, 51.0, 0, rate=1 / 16) == (10, start)  # 62 ms on


def test_backwards_the_frame_due_is_the_first_at_or_after_the_moment() -> None:
    frames = Frames(70)
    start = (0.0, 1000 + 30 * 33)  # played back from frame 30
    assert play_on(frames, start, 0.0, 0, rate=-1.0) == (30, start)
    assert play_on(frames, start, 0.33, 0, rate=-1.0) == (20, start)
    assert play_on(frames, start, 0.34, 0, rate=-1.0) == (20, start)  # 19 not yet
    assert play_on(frames, start, 0.33, 0, rate=-2.0) == (10, start)


def test_backwards_past_the_first_frame_playing_ends() -> None:
    frames = Frames(70)
    start = (0.0, 1000 + 2 * 33)
    assert play_on(frames, start, 0.05, 0, rate=-1.0) == (1, start)
    assert play_on(frames, start, 0.066, 0, rate=-1.0) == (None, start)
    assert play_on(Frames(0), start, 0.0, 0, rate=-1.0) == (None, start)


def test_backwards_a_gap_is_jumped_over_to_the_frame_before_it() -> None:
    frames = Frames(20, gap_after=10)  # frames 0-9, ten minutes, frames 10-19
    start = (0.0, int(frames.ms[15]))
    assert play_on(frames, start, 0.2, 0, rate=-1.0) == (10, start)  # held a while
    place, start = play_on(frames, start, 1.5, 0, rate=-1.0)
    assert (place, start) == (9, (1.5, int(frames.ms[9])))
    assert play_on(frames, start, 1.533, 0, rate=-1.0) == (8, start)


def test_backwards_from_after_the_newest_frame_jumps_to_it_when_far() -> None:
    frames = Frames(10)
    newest = int(frames.ms[-1])
    near = (0.0, newest + 500)  # half a second after it: held, not jumped
    assert play_on(frames, near, 0.0, 0, rate=-1.0) == (9, near)
    place, start = play_on(frames, (0.0, newest + 5000), 0.0, 0, rate=-1.0)
    assert (place, start) == (9, (0.0, newest))


def test_a_speed_is_named_as_its_button_names_it() -> None:
    names = [speed_name(2.0**n) for n in range(-4, 5)]
    assert names == ["x1/16", "x1/8", "x0.25", "x0.5", "x1", "x2", "x4", "x8", "x16"]
    assert (SLOWEST, FASTEST) == (1 / 16, 16.0)


def test_the_moment_due_is_where_playing_went_on_from_and_the_time_since() -> None:
    assert moment_due((10.0, 5_000), 10.5, 1.0) == 5_500
    assert moment_due((10.0, 5_000), 10.5, 4.0) == 7_000
    assert moment_due((10.0, 5_000), 10.5, -0.5) == 4_750
