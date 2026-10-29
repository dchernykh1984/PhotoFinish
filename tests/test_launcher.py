"""Starting a recorder apart from the window, attaching to it, restarting it."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from app import paths, session
from app.recorder import launcher
from app.recorder.launcher import Watchdog, alive, command, heartbeat

ROOT = Path(__file__).resolve().parents[1]


def now_ms() -> int:
    return time.time_ns() // 1_000_000


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    return tmp_path / "video" / "cam1"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    moment = {"now": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: moment["now"])
    return moment


def beat(folder: Path, state: str, age_ms: int = 0) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    info = {"state": state, "heartbeat_ms": now_ms() - age_ms}
    (folder / "recorder.json").write_text(json.dumps(info))


class Process:
    def __init__(self) -> None:
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code


class Spawns:
    def __init__(self) -> None:
        self.processes: list[Process] = []

    def __call__(self, camera_id: str) -> Any:
        assert camera_id == "cam1"
        self.processes.append(Process())
        return self.processes[-1]


def test_a_recorder_that_cannot_be_started_is_tried_again_after_the_pause(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "disk_full", age_ms=86_400_000)  # yesterday's end, not this one's
    spawns = Spawns()
    refused = [OSError("blocked by an antivirus")]

    def spawning(camera_id: str) -> Any:
        if refused:
            raise refused.pop()
        return spawns(camera_id)

    watchdog = Watchdog("cam1", spawning)
    watchdog.start()
    assert watchdog.error == "blocked by an antivirus"
    for moment in (1001, 1002):
        clock["now"] = moment
        watchdog.poll()
    assert len(spawns.processes) == 1
    assert watchdog.error == ""


def test_a_running_recorder_is_attached_not_started_again(folder: Path) -> None:
    beat(folder, "recording")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    assert watchdog.poll() == heartbeat("cam1")
    assert spawns.processes == []


def test_a_recorder_is_started_and_an_old_stop_request_dropped(folder: Path) -> None:
    folder.mkdir(parents=True)
    (folder / "stop.request").touch()
    spawns = Spawns()
    Watchdog("cam1", spawns).start()
    assert len(spawns.processes) == 1
    assert not (folder / "stop.request").exists()


def test_a_dead_recorder_is_started_again_after_the_pause(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    spawns.processes[-1].code = 1
    for moment, started in ((1001, 1), (1001.5, 1), (1002, 2)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started
    spawns.processes[-1].code = 1
    for moment, started in ((1003, 2), (1004.9, 2), (1005, 3)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started


def test_a_starting_recorder_gets_its_time(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    for moment, started in ((1029, 1), (1031, 1), (1032, 2)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started


def test_a_recorder_that_ended_by_itself_is_left_for_the_referee(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "stopped", age_ms=60_000)
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    beat(folder, "disk_full")
    spawns.processes[-1].code = 4
    for moment in (1001, 1100):
        clock["now"] = moment
        assert watchdog.poll() == heartbeat("cam1")
    assert len(spawns.processes) == 1


def test_an_old_end_does_not_hide_a_recorder_that_died(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "stopped", age_ms=60_000)
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    spawns.processes[-1].code = 1
    for moment in (1001, 1002):
        clock["now"] = moment
        watchdog.poll()
    assert len(spawns.processes) == 2


def test_an_attached_recorder_that_dies_is_started_again(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "recording")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    beat(folder, "recording", age_ms=16_000)
    for moment in (1001, 1002):
        clock["now"] = moment
        watchdog.poll()
    assert len(spawns.processes) == 1


def test_a_stop_is_asked_through_the_folder_and_not_undone(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    watchdog.stop()
    assert (folder / "stop.request").exists()
    spawns.processes[-1].code = 0
    clock["now"] = 2000
    watchdog.poll()
    watchdog.poll()
    assert len(spawns.processes) == 1


def test_a_heartbeat_is_read_as_it_is(folder: Path) -> None:
    assert heartbeat("cam1") is None
    folder.mkdir(parents=True)
    (folder / "recorder.json").write_text("[1]")
    assert heartbeat("cam1") is None
    (folder / "recorder.json").write_text("{not json")
    assert heartbeat("cam1") is None
    assert not alive(None)
    assert alive({"state": "connecting", "heartbeat_ms": now_ms()})
    opening = {"state": "connecting", "heartbeat_ms": now_ms() - 11_000}
    assert alive(opening)  # a camera open blocks up to 10 s without a heartbeat
    assert not alive({"state": "recording", "heartbeat_ms": now_ms() - 15_001})
    assert not alive({"state": "stopped", "heartbeat_ms": now_ms()})


def test_the_command_is_this_program(monkeypatch: pytest.MonkeyPatch) -> None:
    assert command("cam1")[1:] == ["-m", "app.main", "--recorder", "cam1"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert command("cam1") == [sys.executable, "--recorder", "cam1"]


def test_a_frozen_build_starts_its_children_as_instances_of_their_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYINSTALLER_RESET_ENVIRONMENT", raising=False)
    assert launcher.child_environment()["PYTHONPATH"] == launcher.package_root()
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in launcher.child_environment()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert launcher.child_environment()["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_a_spawned_recorder_runs_this_program_and_logs_beside_it(
    folder: Path,
) -> None:
    session.save({**session.DEFAULTS, "cameras": []})
    process = launcher.spawn("cam1")
    assert process.wait(timeout=30) == 2
    info = heartbeat("cam1")
    assert info is not None
    assert info["detail"] == "no camera cam1 in the session"
    assert (folder / "recorder.log").exists()


PARENT = """
import time
from app.recorder.launcher import Watchdog
watchdog = Watchdog("cam1")
watchdog.start()
print(watchdog._process.pid, flush=True)
time.sleep(120)
"""


def running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_for(condition: Any, seconds: float = 30) -> None:
    until = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < until, "timed out"
        time.sleep(0.1)


@pytest.mark.skipif(sys.platform == "win32", reason="os.kill(pid, 0) ends it there")
def test_a_recorder_outlives_the_window_that_started_it(tmp_path: Path) -> None:
    camera = {"id": "cam1", "connection": "test", "settings": {"fps": 30}}
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "session.json").write_text(
        json.dumps({**session.DEFAULTS, "cameras": [camera]})
    )
    folder = tmp_path / "video" / "cam1"

    def info() -> dict[str, Any]:
        try:
            return json.loads((folder / "recorder.json").read_text())
        except OSError, ValueError:
            return {}

    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    window = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", PARENT],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert window.stdout is not None
    pid = int(window.stdout.readline())
    try:
        wait_for(lambda: info().get("state") == "recording")
        window.kill()
        window.wait(timeout=10)
        frames = info()["frames"]
        wait_for(lambda: info().get("frames", 0) > frames + 60)
        assert alive(info())
        assert running(pid)
        (folder / "stop.request").touch()
        wait_for(lambda: not running(pid))
        assert info()["state"] == "stopped"
    finally:
        window.kill()
        if running(pid):
            os.kill(pid, signal.SIGKILL)
    assert (folder / "recorder.log").exists()
    assert launcher.ENDED[0] == "stopped"


def test_a_recorder_is_described_as_the_referee_needs() -> None:
    from app.recorder.launcher import describe

    fresh = now_ms()
    assert describe(None) == "not started"
    assert describe({"state": "recording", "heartbeat_ms": fresh, "frames": 5}) == (
        "recording, 5 frames"
    )
    low = {"state": "recording", "heartbeat_ms": fresh, "detail": "low disk"}
    assert describe(low) == "recording, 0 frames, under 2 GB free"
    waiting = {"state": "connecting", "heartbeat_ms": fresh, "detail": "waiting for x"}
    assert describe(waiting) == "connecting: waiting for x"
    assert describe({"state": "recording", "heartbeat_ms": 0}) == "not responding"
    assert describe({"state": "disk_full", "heartbeat_ms": 0}) == (
        "disk full, recording stopped"
    )
    assert describe({"state": "stopped", "heartbeat_ms": 0}) == "stopped"


def test_record_again_before_a_stop_is_heard_withdraws_it(folder: Path) -> None:
    beat(folder, "recording")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.stop()
    assert (folder / "stop.request").exists()
    watchdog.start()  # the recorder has not stopped yet: it records on
    assert not (folder / "stop.request").exists()
    assert spawns.processes == []


def test_a_recorder_that_heard_the_stop_before_it_was_withdrawn_starts_again(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "recording")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.stop()
    watchdog.start()  # attached: it records on, it seemed
    beat(folder, "stopped")  # but it had heard the stop already
    for moment in (1001, 1002):
        clock["now"] = moment
        watchdog.poll()
    assert len(spawns.processes) == 1


def test_a_heartbeat_being_replaced_is_read_again(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import files

    beat(folder, "recording")
    real = Path.read_bytes
    held = [PermissionError("being replaced")]

    def read_bytes(self: Path) -> bytes:
        if held:
            raise held.pop()
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(files.time, "sleep", lambda seconds: None)
    info = heartbeat("cam1")
    assert info is not None
    assert info["state"] == "recording"
