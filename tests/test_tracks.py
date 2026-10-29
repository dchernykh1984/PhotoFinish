"""Riders followed between samples and their crossings of the line (002 US2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import av
import pytest

from app import paths, session
from app.analysis import analyzer
from app.analysis.detector import Box
from app.analysis.tracks import LOST_MS, Tracker, front, refine
from app.interpolation import CENTRE
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import read_time, render, rider_front

START = 1_761_716_120_000  # passes start 2 s after each 10 s


def box(x2: float, width: float = 0.1) -> Box:
    return Box(x2 - width, 0.45, x2, 0.85, 0.9, 0)


def test_a_rider_crossing_between_two_samples_is_one_crossing() -> None:
    tracker = Tracker(CENTRE)
    assert tracker.feed([box(0.25)], ("a", 1, 1000)) == []
    (found,) = tracker.feed([box(0.62)], ("a", 2, 1500))
    assert (found.before, found.after) == (("a", 1, 1000), ("a", 2, 1500))
    assert tracker.feed([box(0.9)], ("b", 3, 2000)) == []


def test_riders_that_do_not_cross_or_vanish_give_nothing() -> None:
    tracker = Tracker(CENTRE)
    tracker.feed([box(0.1), box(0.9)], ("a", 1, 1000))
    assert tracker.feed([box(0.2), box(0.95)], ("a", 2, 1500)) == []
    assert len(tracker.tracks) == 2
    assert tracker.feed([box(0.7)], ("a", 3, 1500 + LOST_MS + 1)) == []
    assert len(tracker.tracks) == 1  # both lost; one new rider
    tracker.feed([box(0.7)], ("a", 4, 5000))  # standing still: no way across
    assert tracker.feed([box(0.7)], ("a", 5, 5500)) == []


def test_the_front_leads_the_way_the_rider_moves() -> None:
    rider = Box(0.2, 0.3, 0.4, 0.9, 1.0, 0)
    assert front(rider, CENTRE, -1.0) == (0.4, 0.6)  # rightwards on this line
    assert front(rider, CENTRE, 1.0) == (0.2, 0.6)
    assert front(rider, CENTRE, 0.0) == pytest.approx((0.3, 0.6))
    across = ((0.0, 0.5), (1.0, 0.5))
    assert front(rider, across, 1.0) == (pytest.approx(0.3), 0.9)


def test_the_frames_between_two_samples_time_the_crossing() -> None:
    tracker = Tracker(CENTRE)
    tracker.feed([box(0.3)], ("s", 0, 0))
    (found,) = tracker.feed([box(0.7)], ("s", 10, 400))
    frames: list[tuple[Any, tuple[str, int, int]]] = [
        (0.31 + k * 0.04, ("s", k, k * 40)) for k in range(1, 10)
    ]

    def riders(x2: Any) -> list[Box]:
        return [box(float(x2))]

    timed = refine(found, frames, riders, CENTRE)
    assert timed == {
        "ms": 190,  # three quarters of the way from frame 4 (0.47) to 5 (0.51)
        "frames": [["s", 4, 160], ["s", 5, 200]],
        "fraction": pytest.approx(0.75),
    }
    nothing_between = refine(found, [], riders, CENTRE)
    assert nothing_between is not None
    assert nothing_between["frames"] == [["s", 0, 0], ["s", 10, 400]]
    assert nothing_between["ms"] == 200


class FakeDetector:
    """Sees the test camera's passing rider exactly where the camera drew it."""

    name, width, height = "fake.onnx", 640, 640

    def __init__(self, path: Path) -> None:
        self.path = path

    def riders(self, frame: av.VideoFrame) -> list[Box]:
        ms = read_time(frame.to_ndarray(format="rgb24"))
        lead = rider_front(ms, 640)
        if lead is None or lead <= 0:
            return []
        return [Box(max(lead - 80, 0) / 640, 0.45, min(lead, 640) / 640, 0.85, 0.9, 0)]


def test_each_crossing_of_the_centre_line_is_suggested_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """002 SC-003: within one frame interval of the true crossing."""
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(analyzer, "Detector", FakeDetector)
    camera = {"id": "cam1", "connection": "test", "settings": {"fps": 25}}
    analysis = {"on": True, "model": "fake.onnx"}
    session.save({**session.DEFAULTS, "cameras": [camera], "analysis": analysis})
    folder = tmp_path / "video" / "cam1"
    writer = SegmentWriter(folder, fps=25)
    for k in range(750):
        writer.write(render(START + k * 40, 640, 360, "passes"), START + k * 40)
    writer.close()
    assert analyzer.run("cam1", stop=lambda: False, once=True) == 0
    lines = (folder / "suggestions.jsonl").read_text().splitlines()
    suggested = [json.loads(line) for line in lines]
    assert len(suggested) == 3
    for n, found in enumerate(suggested):
        true = START + n * 10_000 + 2_000 + 400 * 1500 / 720  # its front at 320 px
        assert abs(found["ms"] - true) < 40
        assert (found["camera"], found["model"]) == ("cam1", "fake.onnx")
        assert found["frames"][1][2] - found["frames"][0][2] == 40
        assert 0 <= found["fraction"] <= 1
        assert found["id"] == f"cam1-{found['ms']}"
