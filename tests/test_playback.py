"""Which frame playing shows, by the clock."""

from __future__ import annotations

import numpy as np

from app.playback import frame_due


class Frames:
    """Frames 33 ms apart, as a 30 fps camera records them."""

    def __init__(self, count: int, first: int = 1000) -> None:
        self.ms = first + 33 * np.arange(count, dtype=np.int64)

    def __len__(self) -> int:
        return len(self.ms)

    def nearest(self, ms: int, within: int | None = None) -> int | None:
        return int(np.abs(self.ms - ms).argmin())


def test_the_frame_due_follows_the_clock_from_where_playing_started() -> None:
    frames = Frames(70)
    start = (50.0, 1000 + 9 * 33)  # played from frame 9
    assert frame_due(frames, start, 50.0, 0) == 9
    assert frame_due(frames, start, 50.33, 0) == 19  # ten frames a third of a second on
    assert frame_due(frames, start, 50.001, 0) == 9  # not due yet: still frame 9


def test_the_cameras_offset_is_added_to_its_frames_times() -> None:
    frames = Frames(70)
    offset = 500  # the camera's frames show 500 ms later on the video's time
    start = (0.0, 1000 + 9 * 33 + offset)
    assert frame_due(frames, start, 0.33, offset) == 19


def test_past_the_newest_frame_playing_is_live() -> None:
    frames = Frames(70)
    newest = 1000 + 69 * 33
    assert frame_due(frames, (0.0, newest - 100), 0.05, 0) == 67
    assert frame_due(frames, (0.0, newest - 100), 0.1, 0) is None
    assert frame_due(frames, (0.0, newest - 100), 0.1, 200) == 63  # offset: not yet
    assert frame_due(Frames(0), (0.0, 0), 1.0, 0) is None
