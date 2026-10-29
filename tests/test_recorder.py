"""A camera's recorder: heartbeat, stop request, reconnects, the disk."""

from __future__ import annotations

import errno
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import av
import numpy as np
import pytest

import app.recorder as recorder
from app import paths, session
from app.recorder import Backoff, Heartbeat, SteadyClock, run
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import read_time, render
from tests.test_segments import make_h264

ROOT = Path(__file__).resolve().parents[1]
START = 1_761_716_129_587


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    camera = {"id": "cam1", "connection": "test", "settings": {"fps": 30}}
    session.save({**session.DEFAULTS, "cameras": [camera]})
    return tmp_path / "video" / "cam1"


def test_the_pause_doubles_to_thirty_seconds_and_resets_after_a_good_run() -> None:
    backoff = Backoff()
    assert [backoff.failed(0) for _ in range(7)] == [1, 2, 4, 8, 16, 30, 30]
    backoff.running(100)
    assert backoff.failed(129) == 30
    backoff.running(200)
    backoff.running(220)
    assert backoff.failed(230) == 1
    assert backoff.failed(231) == 2


def test_the_steady_clock_does_not_follow_the_computer_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SteadyClock()
    first = clock()
    assert abs(first - time.time() * 1000) < 1000
    monkeypatch.setattr(time, "time_ns", lambda: 0)
    assert clock() >= first


class Camera:
    """A source: ``count`` frames from ``start``, then ``then`` (raised) or the end;
    a stop is asked for after ``stop_after`` frames."""

    fps = 30.0

    def __init__(
        self,
        folder: Path,
        start: int,
        count: int,
        then: Exception | None = None,
        stop_after: int | None = None,
    ) -> None:
        self.folder, self.start, self.count = folder, start, count
        self.then, self.stop_after = then, stop_after

    def frames(self) -> Iterator[tuple[np.ndarray, int]]:
        for k in range(self.count):
            if k == self.stop_after:
                (self.folder / "stop.request").touch()
            ms = self.start + k * 33
            yield render(ms, 640, 360), ms
        if self.then is not None:
            raise self.then


def cameras(monkeypatch: pytest.MonkeyPatch, *opened: Any) -> list[str]:
    """Each opening of the camera gives the next of ``opened``; the states the
    heartbeat went through are returned as they come."""
    queue = list(opened)
    monkeypatch.setattr(recorder, "open_source", lambda camera, clock: queue.pop(0))
    monkeypatch.setattr(Backoff, "failed", lambda self, now: 0.01)
    states: list[str] = []
    real = Heartbeat.beat

    def beat(self: Heartbeat, **changes: Any) -> None:
        real(self, **changes)
        if not states or states[-1] != self.info["state"]:
            states.append(self.info["state"])

    monkeypatch.setattr(Heartbeat, "beat", beat)
    return states


def heartbeat(folder: Path) -> dict[str, Any]:
    return json.loads((folder / "recorder.json").read_text())


def test_a_stop_request_closes_the_segment_and_ends_the_recorder(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = cameras(monkeypatch, Camera(folder, START, 100, stop_after=70))
    assert run("cam1") == 0
    assert states == ["connecting", "recording", "stopped"]
    beat = heartbeat(folder)
    assert (beat["state"], beat["frames"], beat["pid"]) == ("stopped", 71, os.getpid())
    assert beat["segments"] == 3  # the one closed on the stop counted too
    assert beat["connection"] == "test"
    assert not (folder / "stop.request").exists()
    assert not (folder / "current.mkv").exists()
    assert len(list(folder.glob("*-*-*.mkv"))) == 3


def test_a_camera_that_fails_is_opened_again_and_the_gap_kept(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = cameras(
        monkeypatch,
        Camera(folder, START, 10, then=OSError("camera gone")),
        Camera(folder, START + 5000, 10),
        Camera(folder, START + 9000, 10, stop_after=5),
    )
    assert run("cam1") == 0
    assert states == [
        "connecting",
        "recording",
        "reconnecting",
        "connecting",
        "recording",
        "reconnecting",
        "connecting",
        "recording",
        "stopped",
    ]
    gaps = (folder / "gaps.txt").read_text().splitlines()
    assert gaps == [
        f"{START + 297} {START + 5000} reconnect",
        f"{START + 5297} {START + 9000} reconnect",
    ]


def test_a_stop_during_the_pause_ends_the_recorder(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = cameras(monkeypatch, Camera(folder, START, 3, then=OSError()))
    monkeypatch.setattr(Backoff, "failed", lambda self, now: 5.0)
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        (folder / "stop.request").touch()

    assert run("cam1", sleep=sleep) == 0
    assert states[-2:] == ["reconnecting", "stopped"]
    assert heartbeat(folder)["detail"] == ""
    assert slept == [0.1]


def test_a_full_disk_stops_the_recorder_and_says_so(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cameras(monkeypatch, Camera(folder, START, 10))

    def full(self: SegmentWriter, image: np.ndarray, ms: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(SegmentWriter, "write", full)
    assert run("cam1") == 4
    assert heartbeat(folder)["state"] == "disk_full"


def test_low_disk_is_said_while_recording(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beat = Heartbeat(folder.parent, "test")
    free = {"bytes": recorder.LOW_DISK - 1}
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: SimpleNamespace(free=free["bytes"])
    )
    folder.parent.mkdir(parents=True, exist_ok=True)
    beat.beat(state="recording")
    assert heartbeat(folder.parent)["detail"] == "low disk"
    free["bytes"] = recorder.LOW_DISK
    beat.beat(frames=1)
    assert heartbeat(folder.parent)["detail"] == "low disk"  # within the second
    beat._written -= 1
    beat.beat(frames=2)
    assert heartbeat(folder.parent)["detail"] == ""


def test_a_heartbeat_that_cannot_be_written_waits_for_the_next(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder.mkdir(parents=True)
    beat = Heartbeat(folder, "test")

    def refuse(self: Path, target: Path) -> Path:
        raise PermissionError("held")

    monkeypatch.setattr(Path, "replace", refuse)
    beat.beat(state="recording")
    assert not (folder / "recorder.json").exists()


def test_a_camera_that_cannot_be_recorded_fails_at_once(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.save(
        {**session.DEFAULTS, "cameras": [{"id": "cam1", "connection": "pigeon"}]}
    )
    assert run("cam1") == 2
    assert heartbeat(folder)["state"] == "failed"
    assert "pigeon" in heartbeat(folder)["detail"]
    assert run("cam2") == 2
    assert (
        heartbeat(folder.parent / "cam2")["detail"] == "no camera cam2 in the session"
    )
    assert run("../cam1") == 2


def test_a_camera_with_a_recorder_gets_no_second_one(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder.mkdir(parents=True)
    held = recorder._lock(folder / "recorder.lock")
    assert held is not None
    try:
        assert run("cam1") == 3
    finally:
        held.close()
    assert not (folder / "recorder.json").exists()


def test_a_camera_that_ends_is_opened_again(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = cameras(
        monkeypatch,
        Camera(folder, START, 3),
        Camera(folder, START + 1000, 3, stop_after=1),
    )
    assert run("cam1") == 0
    assert "reconnecting" in states


def start_recorder(base: Path) -> subprocess.Popen[bytes]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.Popen(
        [sys.executable, "-m", "app.main", "--recorder", "cam1"], cwd=base, env=env
    )


def wait_for(condition: Any, seconds: float = 30) -> None:
    until = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < until, "timed out"
        time.sleep(0.1)


def test_a_recorder_process_records_the_test_camera(tmp_path: Path) -> None:
    # 10 fps: a test run busy on every core must not make the camera drop frames.
    camera = {"id": "cam1", "connection": "test", "settings": {"fps": 10}}
    data = tmp_path / "data"
    data.mkdir()
    (data / "session.json").write_text(
        json.dumps({**session.DEFAULTS, "cameras": [camera]})
    )
    folder = tmp_path / "video" / "cam1"
    process = start_recorder(tmp_path)
    try:
        wait_for(lambda: len(list(folder.glob("*-*-*.mkv"))) >= 2)
        assert heartbeat(folder)["state"] == "recording"
        assert heartbeat(folder)["pid"] == process.pid
        assert start_recorder(tmp_path).wait(timeout=30) == 3
        (folder / "stop.request").touch()
        assert process.wait(timeout=30) == 0
    finally:
        process.kill()
    assert heartbeat(folder)["state"] == "stopped"
    lines = sorted(
        int(line.split()[1])
        for path in folder.glob("*-*-*.times")
        for line in path.read_text().splitlines()
    )
    assert max(b - a for a, b in itertools.pairwise(lines)) < 1000
    first = min(folder.glob("*-*-*.mkv"))
    with av.open(str(first)) as container:
        frame = next(container.decode(video=0))
        assert read_time(frame.to_ndarray(format="rgb24")) == lines[0]


def test_a_write_that_fails_otherwise_is_tried_again(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = cameras(
        monkeypatch,
        Camera(folder, START, 3),
        Camera(folder, START + 1000, 3, stop_after=1),
    )
    real = SegmentWriter.write
    failures = [OSError(errno.EACCES, "Permission denied")]

    def flaky(self: SegmentWriter, image: np.ndarray, ms: int) -> None:
        if failures:
            raise failures.pop()
        real(self, image, ms)

    monkeypatch.setattr(SegmentWriter, "write", flaky)
    assert run("cam1") == 0
    assert states[:3] == ["connecting", "reconnecting", "connecting"]


class Network:
    """A network camera: a wait for it to call in, then its packets."""

    fps = 30.0
    waiting = "waiting for rtmp://10.0.0.5:1935/live/x"

    def __init__(self, folder: Path, path: Path) -> None:
        self.folder, self.path = folder, path

    def frames(self) -> Iterator[Any]:
        yield None
        with av.open(str(self.path)) as container:
            stream = container.streams.video[0]
            unit = float(stream.time_base or 0) * 1000
            for packet in container.demux(stream):
                if packet.pts is not None:
                    yield packet, START + round(packet.pts * unit)
        (self.folder / "stop.request").touch()
        yield None


def test_a_network_camera_is_waited_for_and_its_packets_kept(
    folder: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    make_h264(tmp_path / "camera.mp4", 70)
    cameras(monkeypatch, Network(folder, tmp_path / "camera.mp4"))
    details: list[str] = []
    real = Heartbeat.beat

    def beat(self: Heartbeat, **changes: Any) -> None:
        real(self, **changes)
        details.append(self.info["detail"])

    monkeypatch.setattr(Heartbeat, "beat", beat)
    assert run("cam1") == 0
    assert "waiting for rtmp://10.0.0.5:1935/live/x" in details
    assert heartbeat(folder)["frames"] == 70
    assert len(list(folder.glob("*-*-*.mkv"))) == 3
