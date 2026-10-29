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


def stretches(folder: Path) -> list[list[int]]:
    found: list[list[int]] = []
    for path in sorted(folder.glob("*.activity.json")):
        for start, end in json.loads(path.read_text())["stretches"]:
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
    assert not analyzer.unanalysed(folder)
    found = stretches(folder)
    assert len(found) == 3
    for n, (start, end) in enumerate(found):
        assert START + n * 10_000 + 2_000 <= start <= end <= START + n * 10_000 + 3_500
    progress = json.loads((folder / "analyzer.json").read_text())
    assert (progress["state"], progress["done_ms"]) == ("waiting", START + 29_900)
    written = {p: p.stat().st_mtime_ns for p in folder.glob("*.activity.json")}
    analyzer.run("cam1", stop=lambda: False, once=True)  # nothing is done twice
    assert {p: p.stat().st_mtime_ns for p in folder.glob("*.activity.json")} == written


def test_leaves_alone_give_no_stretch(base: Path) -> None:
    folder = camera(base, "sway", 10)
    analyzer.run("cam1", stop=lambda: False, once=True)
    assert stretches(folder) == []


def test_a_segment_that_cannot_be_read_is_noted_and_left(base: Path) -> None:
    folder = camera(base, "sway", 2)
    broken = folder / "20000101-000000-9999.mkv"
    broken.write_bytes(b"not a video")
    analyzer.run("cam1", stop=lambda: False, once=True)
    assert "error" in json.loads(broken.with_suffix(".activity.json").read_text())


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
        while analyzer.unanalysed(folder):
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
