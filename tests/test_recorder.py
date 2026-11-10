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
from typing import Any, ClassVar

import av
import numpy as np
import pytest

import app.recorder as recorder
from app import paths, session
from app.recorder import Backoff, Heartbeat, SteadyClock, run
from app.recorder import segments as segments_module
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import read_time, render
from tests.test_segments import killed_while_recording, make_h264

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


def test_the_steady_clock_keeps_order_and_wakes_up_with_the_computer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"wall": 1_000_000_000_000_000_000, "steady": 5_000_000_000}
    monkeypatch.setattr(time, "time_ns", lambda: now["wall"])
    monkeypatch.setattr(time, "monotonic_ns", lambda: now["steady"])
    clock = SteadyClock()
    first = clock()
    assert first == now["wall"] // 1_000_000
    now["wall"] -= 3_600_000_000_000  # the clock set back an hour
    now["steady"] += 1_000_000_000
    assert clock() == first + 1000  # not followed: frames keep their order
    now["wall"] += 3_600_000_000_000 + 121_000_000_000  # slept two minutes
    now["steady"] += 1_000_000_000  # the steady clock did not count them
    assert clock() == first + 121_000  # read again: on the computer's time
    now["wall"] += 1_500_000_000  # a little ahead is no sleep: followed slowly
    now["steady"] += 1_000_000_000
    assert clock() == first + 122_001  # a millisecond for the second passed


def test_the_steady_clock_follows_a_drifting_computer_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for drift in (1.00005, 0.99995):  # 50 ppm either way, a whole race day
        now = {"wall": 2_000_000_000_000_000_000, "steady": 7_000_000_000}
        monkeypatch.setattr(time, "time_ns", lambda now=now: now["wall"])
        monkeypatch.setattr(time, "monotonic_ns", lambda now=now: now["steady"])
        clock, last = SteadyClock(), 0
        for _ in range(12 * 60):  # every minute for twelve hours
            now["steady"] += 60_000_000_000
            now["wall"] += round(60_000_000_000 * drift)
            moment = clock()
            assert moment > last
            last = moment
        assert abs(last - now["wall"] // 1_000_000) <= 1


def test_the_steady_clock_reads_to_the_microsecond_for_a_phone_s_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"wall": 1_794_329_044_562_000_000, "steady": 5_000_000_000}
    monkeypatch.setattr(time, "time_ns", lambda: now["wall"])
    monkeypatch.setattr(time, "monotonic_ns", lambda: now["steady"])
    clock = SteadyClock()
    now["wall"] += 1_234_000
    now["steady"] += 1_234_000
    assert clock.micros() == now["wall"] // 1000  # 1.234 ms on, to the microsecond
    assert clock() == now["wall"] // 1_000_000


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
    assert states == ["starting", "connecting", "recording", "stopped"]
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
        "starting",
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


def test_a_full_disk_met_as_the_writer_recovers_stops_the_recorder_and_says_so(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopping = Camera(folder, START, 10, stop_after=0)
    cameras(monkeypatch, Camera(folder, START, 10), stopping)

    def full(folder: Path) -> list[str]:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(recorder, "recover", full)  # at the start, said by no one
    monkeypatch.setattr(segments_module, "recover", full)  # and the writer's own
    assert run("cam1") == 4  # not taken for the camera, tried again for ever
    assert heartbeat(folder)["state"] == "disk_full"


def test_a_full_disk_is_said_though_no_new_file_can_be_written(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder.mkdir(parents=True)
    beat = Heartbeat(folder, "test")
    beat.beat(state="recording")
    real = Path.open

    def full(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name.endswith(".tmp"):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", full)
    beat.beat(state="disk_full", detail="the disk is full")
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


def test_a_starting_recorder_shows_what_a_crash_left_before_its_camera_is_back(
    folder: Path,
) -> None:
    killed_while_recording(folder, 20, START)
    session.save({**session.DEFAULTS, "cameras": []})  # its camera gone meanwhile
    assert run("cam1") == 2
    (name,) = (folder / "segments.txt").read_text().split()
    assert len((folder / f"{name}.times").read_text().splitlines()) >= 20 - 4
    assert not list(folder.glob("current.*"))


def test_a_recorder_sees_to_what_a_crash_left_once_as_it_starts(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.recorder import segments as written

    looked: list[Path] = []
    real = written._list_missing

    def counted(folder: Path) -> list[str]:
        looked.append(folder)
        return real(folder)

    monkeypatch.setattr(written, "_list_missing", counted)
    cameras(monkeypatch, Camera(folder, START, 100, stop_after=10))
    assert run("cam1") == 0
    assert looked == [folder]  # one look through a long day's folder, not two


def test_a_recovery_that_fails_at_the_start_leaves_the_recorder_running(
    folder: Path,
) -> None:
    folder.mkdir(parents=True)
    (folder / "segments.txt").write_bytes(b"\xd0\xb9\n")  # not ASCII
    session.save({**session.DEFAULTS, "cameras": []})
    assert run("cam1") == 2
    assert heartbeat(folder)["detail"] == "no camera cam1 in the session"


def test_a_list_with_bytes_that_are_not_ascii_does_not_stop_the_recording(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder.mkdir(parents=True)
    (folder / "segments.txt").write_bytes(b"\xd0\xb9\n")
    cameras(monkeypatch, Camera(folder, START, 100, stop_after=40))
    assert run("cam1") == 0
    assert list(folder.glob("*-*-*.mkv"))


def test_a_starting_recorder_says_so_before_it_sees_to_a_crash(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder.mkdir(parents=True)
    (folder / "recorder.json").write_text('{"state": "recording", "pid": 1}')
    seen: list[dict[str, Any]] = []

    def recovering(folder: Path) -> list[str]:
        seen.append(heartbeat(folder))
        return []

    monkeypatch.setattr(recorder, "recover", recovering)
    session.save({**session.DEFAULTS, "cameras": []})
    run("cam1")
    assert (seen[0]["state"], seen[0]["pid"]) == ("starting", os.getpid())


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
    assert states[:4] == ["starting", "connecting", "reconnecting", "connecting"]


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


class Responder:
    """A stand-in for the clock exchange: what it was opened with, and its close."""

    made: ClassVar[list[Responder]] = []  # each test sets its own list

    def __init__(self, port: int, micros: Any) -> None:
        self.port, self.micros, self.closed = port, micros, False
        self.made.append(self)

    def close(self) -> None:
        self.closed = True


def phone_session() -> None:
    camera = {
        "id": "cam1",
        "connection": "rtmp",
        "settings": {"port": 1999, "path": "live/x"},
    }
    session.save({**session.DEFAULTS, "cameras": [camera]})


def test_a_phone_s_clock_exchange_is_answered_while_its_recorder_runs(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    phone_session()
    monkeypatch.setattr(Responder, "made", [])
    monkeypatch.setattr(recorder, "ClockResponder", Responder)
    cameras(monkeypatch, Camera(folder, START, 5, stop_after=4))
    assert run("cam1", clock=lambda: START) == 0
    [responder] = Responder.made
    assert responder.port == 1999
    assert responder.micros() == START * 1000  # the recorder's clock, in us
    assert responder.closed


def test_a_phone_whose_exchange_port_is_taken_is_still_recorded(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    phone_session()

    def taken(port: int, micros: Any) -> None:
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(recorder, "ClockResponder", taken)
    cameras(monkeypatch, Camera(folder, START, 5, stop_after=4))
    assert run("cam1") == 0
    assert heartbeat(folder)["frames"] == 5


def test_another_camera_gets_no_clock_exchange(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Responder, "made", [])
    monkeypatch.setattr(recorder, "ClockResponder", Responder)
    cameras(monkeypatch, Camera(folder, START, 3, stop_after=2))
    assert run("cam1") == 0
    assert Responder.made == []


def test_low_disk_does_not_make_the_heartbeat_write_at_every_frame(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cameras(monkeypatch, Camera(folder, START, 60, stop_after=59))
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: SimpleNamespace(free=recorder.LOW_DISK - 1)
    )
    written: list[float] = []
    real = Path.replace

    def replace(self: Path, target: Path) -> Path:
        if Path(target).name == "recorder.json":
            written.append(time.monotonic())
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    started = time.monotonic()
    assert run("cam1") == 0
    seconds = time.monotonic() - started
    assert len(written) <= 6 + 2 * seconds  # the changes of state, then once a second


def test_a_segment_that_cannot_be_closed_does_not_end_the_recording(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = cameras(
        monkeypatch,
        Camera(folder, START, 10, then=OSError("camera gone")),
        Camera(folder, START + 5000, 10, stop_after=5),
    )
    real = SegmentWriter.close
    broken = [av.FFmpegError(5, "flush failed")]

    def close(self: SegmentWriter) -> None:
        if broken:
            raise broken.pop()
        real(self)

    monkeypatch.setattr(SegmentWriter, "close", close)
    assert run("cam1") == 0
    assert states[-1] == "stopped"
    assert "reconnecting" in states
