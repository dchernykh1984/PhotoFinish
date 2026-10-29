"""The analyser process: each segment indexed once, stopped with its window."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from app import paths, session
from app.analysis import analyzer
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import render

ROOT = Path(__file__).resolve().parents[1]
START = 1_761_716_120_000


def camera(base: Path, scene: str, seconds: int) -> Path:
    """The test camera recorded at 10 fps; the camera in the session with a zone."""
    settings = {"fps": 10, "scene": scene}
    zone = [[0.35, 0.25], [0.65, 0.9]]
    cameras = [{"id": "cam1", "connection": "test", "settings": settings, "zone": zone}]
    session.save({**session.DEFAULTS, "cameras": cameras})
    folder = base / "video" / "cam1"
    writer = SegmentWriter(folder, fps=10)
    for k in range(seconds * 10):
        ms = START + k * 100
        writer.write(render(ms, 640, 360, scene), ms)
    writer.close()
    return folder


def activity(folder: Path) -> list[dict[str, Any]]:
    lines = (folder / "activity.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def unanalysed(folder: Path) -> set[str]:
    """The segments listed and not analysed yet."""
    listed = set((folder / "segments.txt").read_text().split())
    return listed - analyzer.analysed(folder)


def stretches(folder: Path) -> list[list[int]]:
    found: list[list[int]] = []
    for segment in activity(folder):
        for start, end in segment["stretches"]:
            if found and start <= found[-1][1] + 1000:
                found[-1][1] = max(found[-1][1], end)
            else:
                found.append([start, end])
    return found


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    return tmp_path


def test_a_recording_with_three_passes_has_three_stretches(base: Path) -> None:
    folder = camera(base, "passes", 30)
    assert analyzer.run("cam1", stop=lambda: False, once=True) == 0
    assert not unanalysed(folder)
    found = stretches(folder)
    assert len(found) == 3
    for n, (start, end) in enumerate(found):
        assert START + n * 10_000 + 2_000 <= start <= end <= START + n * 10_000 + 3_500
    progress = json.loads((folder / "analyzer.json").read_text())
    assert (progress["state"], progress["done_ms"]) == ("waiting", START + 29_900)
    written = (folder / "activity.jsonl").read_bytes()
    assert [a["segment"] for a in activity(folder)] == (
        (folder / "segments.txt").read_text().split()
    )
    analyzer.run("cam1", stop=lambda: False, once=True)  # nothing is done twice
    assert (folder / "activity.jsonl").read_bytes() == written


def test_leaves_alone_give_no_stretch(base: Path) -> None:
    folder = camera(base, "sway", 10)
    analyzer.run("cam1", stop=lambda: False, once=True)
    assert stretches(folder) == []


def test_a_segment_that_cannot_be_read_is_noted_and_left(base: Path) -> None:
    folder = camera(base, "sway", 2)
    broken = folder / "20000101-000000-9999.mkv"
    broken.write_bytes(b"not a video")
    with (folder / "segments.txt").open("a") as f:
        f.write(broken.stem + "\n")
    analyzer.run("cam1", stop=lambda: False, once=True)
    (noted,) = [a for a in activity(folder) if a["segment"] == broken.stem]
    assert "error" in noted
    assert broken.stem in analyzer.analysed(folder)


def test_an_analyser_waits_for_segments_and_stops_when_asked(base: Path) -> None:
    camera(base, "sway", 1)
    asked = iter([False, False, False, True])
    slept: list[float] = []
    assert analyzer.run("cam1", stop=lambda: next(asked), sleep=slept.append) == 0
    assert slept == [1]
    assert analyzer.run("../cam1") == 2
    assert analyzer.run("cam9") == 2


def test_the_analyser_process_stops_when_its_window_is_gone(base: Path) -> None:
    folder = camera(base, "sway", 3)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    process = subprocess.Popen(
        [sys.executable, "-m", "app.main", "--analyzer", "cam1"],
        cwd=base,
        env=env,
        stdin=subprocess.PIPE,
    )
    try:
        until = time.monotonic() + 30
        while unanalysed(folder):
            assert time.monotonic() < until, "timed out"
            time.sleep(0.1)
        assert process.poll() is None  # it waits for more
        assert process.stdin is not None
        process.stdin.close()  # the window is gone
        assert process.wait(timeout=30) == 0
    finally:
        process.kill()


def test_stdin_closed_tells_the_window_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    class Closed:
        class buffer:  # noqa: N801 - as sys.stdin has it
            @staticmethod
            def read(size: int) -> bytes:
                return b""

    monkeypatch.setattr(sys, "stdin", Closed)
    gone = analyzer._window_gone()
    until = time.monotonic() + 5
    while not gone():
        assert time.monotonic() < until
        time.sleep(0.01)
    monkeypatch.setattr(sys, "stdin", None)
    never = analyzer._window_gone()
    time.sleep(0.05)
    assert not never()


def test_progress_keeps_how_far_it_got(base: Path) -> None:
    folder = base / "video" / "cam1"
    folder.mkdir(parents=True)
    analyzer._progress(folder, "analysing", 1000)
    analyzer._progress(folder, "waiting")
    info: dict[str, Any] = json.loads((folder / "analyzer.json").read_text())
    assert (info["state"], info["done_ms"]) == ("waiting", 1000)


def test_lines_of_activity_that_name_no_segment_are_passed_over(tmp_path: Path) -> None:
    (tmp_path / "activity.jsonl").write_text(
        'not json\n{"stretches": []}\n{"segment": "a"}\n'
    )
    assert analyzer.analysed(tmp_path) == {"a"}


def test_a_segment_held_a_moment_is_tried_again(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = camera(base, "sway", 1)
    real = analyzer.av.open
    held = [PermissionError(13, "held by a virus scanner")]

    def opening(path: str, *args: Any, **kwargs: Any) -> Any:
        if held:
            raise held.pop()
        return real(path, *args, **kwargs)

    monkeypatch.setattr(analyzer.av, "open", opening)
    slept: list[float] = []
    assert analyzer.run("cam1", stop=lambda: False, once=True, sleep=slept.append) == 0
    assert slept == [1]
    assert [("error" in a) for a in activity(folder)] == [False]


def test_a_segment_tried_again_comes_before_the_segments_after_it(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = camera(base, "sway", 2)
    real = analyzer.av.open
    held = [PermissionError(13, "held by a virus scanner")]

    def opening(path: str, *args: Any, **kwargs: Any) -> Any:
        if held:
            raise held.pop()
        return real(path, *args, **kwargs)

    monkeypatch.setattr(analyzer.av, "open", opening)
    assert (
        analyzer.run("cam1", stop=lambda: False, once=True, sleep=lambda _: None) == 0
    )
    listed = (folder / "segments.txt").read_text().split()
    analysed = activity(folder)
    assert len(listed) > 1
    assert [a["segment"] for a in analysed] == listed
    assert all(a["first_ms"] is not None for a in analysed)  # its frames looked at


def test_a_segment_that_fails_partway_is_tried_again_as_if_never_begun(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = camera(base, "passes", 3)
    made: list[Any] = []
    real_watch = analyzer._watch

    def watch(*args: Any) -> Any:
        made.append(real_watch(*args))
        return made[-1]

    monkeypatch.setattr(analyzer, "_watch", watch)
    assert analyzer.run("cam1", stop=lambda: False, once=True) == 0
    clean, found = made[-1].motion, stretches(folder)
    (folder / "activity.jsonl").unlink()
    real_feed = analyzer.MotionWatch.feed
    fed = [0]

    def feed(self: Any, frame: Any, ref: Any) -> int | None:
        fed[0] += 1
        if fed[0] == 8:  # in the second segment, once
            raise OSError("read error")
        return real_feed(self, frame, ref)

    monkeypatch.setattr(analyzer.MotionWatch, "feed", feed)
    assert (
        analyzer.run("cam1", stop=lambda: False, once=True, sleep=lambda _: None) == 0
    )
    again = made[-1].motion
    assert (again._background == clean._background).all()
    assert again._track == clean._track
    assert stretches(folder) == found


def test_a_segment_that_stays_unreadable_is_noted_after_its_tries(base: Path) -> None:
    folder = camera(base, "sway", 1)
    for times in folder.glob("*-*-*.times"):
        times.unlink()  # its frame times lost
    slept: list[float] = []
    assert analyzer.run("cam1", stop=lambda: False, once=True, sleep=slept.append) == 0
    assert len(slept) == analyzer.TRIES - 1
    (noted,) = activity(folder)
    assert "cannot be read" in noted["error"]
