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


class TwoAbreast(FakeDetector):
    """Two riders side by side: the same front, one above the other."""

    def riders(self, frame: av.VideoFrame) -> list[Box]:
        return [
            Box(found.x1, top, found.x2, top + 0.3, found.score, found.kind)
            for found in super().riders(frame)
            for top in (0.1, 0.55)
        ]


def suggested_by(
    detector: type[FakeDetector], frames: int, base: Path, monkeypatch: Any
) -> list[dict[str, Any]]:
    """The crossings suggested over the test camera's passes, 25 frames a second."""
    monkeypatch.setattr(paths, "base_dir", lambda: base)
    monkeypatch.setattr(analyzer, "Detector", detector)
    camera = {"id": "cam1", "connection": "test", "settings": {"fps": 25}}
    analysis = {"on": True, "model": "fake.onnx"}
    session.save({**session.DEFAULTS, "cameras": [camera], "analysis": analysis})
    folder = base / "video" / "cam1"
    writer = SegmentWriter(folder, fps=25)
    for k in range(frames):
        writer.write(render(START + k * 40, 640, 360, "passes"), START + k * 40)
    writer.close()
    assert analyzer.run("cam1", stop=lambda: False, once=True) == 0
    lines = (folder / "suggestions.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_riders_crossing_abreast_are_suggested_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = suggested_by(TwoAbreast, 150, tmp_path, monkeypatch)
    assert first["ms"] == second["ms"]
    assert (first["id"], second["id"]) == (
        f"cam1-{first['ms']}",
        f"cam1-{first['ms']}-2",
    )


def test_each_crossing_of_the_centre_line_is_suggested_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """002 SC-003: within one frame interval of the true crossing."""
    suggested = suggested_by(FakeDetector, 750, tmp_path, monkeypatch)
    assert len(suggested) == 3
    for n, found in enumerate(suggested):
        true = START + n * 10_000 + 2_000 + 400 * 1500 / 720  # its front at 320 px
        assert abs(found["ms"] - true) < 40
        assert (found["camera"], found["model"]) == ("cam1", "fake.onnx")
        assert found["frames"][1][2] - found["frames"][0][2] == 40
        assert 0 <= found["fraction"] <= 1
        assert found["id"] == f"cam1-{found['ms']}"


class FakeReader:
    """Reads 27 in any rider's box, and says what it was given."""

    def __init__(self) -> None:
        self.given: list[tuple[int, ...]] = []

    def read(self, rgb: Any) -> tuple[str, float]:
        self.given.append(rgb.shape)
        return "27", 0.9876


def test_a_crossing_carries_the_number_read_in_the_rider_s_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """006 FR-002: read once, at the crossing, in the rider's box."""
    reader = FakeReader()
    monkeypatch.setattr(analyzer, "_reader", lambda: reader)
    suggested = suggested_by(FakeDetector, 300, tmp_path, monkeypatch)
    assert suggested and all(s["number"] == "27" for s in suggested)
    assert suggested[0]["number_sure"] == 0.988
    assert len(reader.given) == len(suggested)
    height, width, _ = reader.given[0]
    assert height < 360 and width < 640  # the box, not the frame


def test_riders_crossing_on_one_sample_are_read_on_one_picture_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pictures: list[Any] = []

    class Kept(FakeReader):
        def read(self, rgb: Any) -> tuple[str, float]:
            pictures.append(rgb.base)  # the picture the rider's box was cut from
            return super().read(rgb)

    monkeypatch.setattr(analyzer, "_reader", Kept)
    first, second = suggested_by(TwoAbreast, 150, tmp_path, monkeypatch)
    assert first["ms"] == second["ms"]
    assert len(pictures) == 2
    assert pictures[0] is pictures[1]  # converted once for both


def test_a_reader_that_cannot_be_loaded_is_said_and_costs_the_numbers_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unloadable() -> Any:
        raise RuntimeError("onnxruntime: bad model")

    monkeypatch.setattr(analyzer, "_reader", unloadable)
    suggested = suggested_by(FakeDetector, 300, tmp_path, monkeypatch)
    assert suggested and all("number" not in s for s in suggested)
    progress = json.loads((tmp_path / "video" / "cam1" / "analyzer.json").read_text())
    said = "the number reader cannot be loaded: onnxruntime: bad model"
    assert progress["numbers"] == said


def test_a_reader_that_fails_costs_the_number_not_the_crossing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(FakeReader):
        def read(self, rgb: Any) -> tuple[str, float]:
            raise RuntimeError("onnxruntime: bad input")

    monkeypatch.setattr(analyzer, "_reader", Broken)
    suggested = suggested_by(FakeDetector, 300, tmp_path, monkeypatch)
    assert suggested and all("number" not in s for s in suggested)
