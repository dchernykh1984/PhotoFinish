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
from app.version import version as program_version

ROOT = Path(__file__).resolve().parents[1]
THIS = program_version()  # a recorder of this program's, as most tests have it


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


def beat(
    folder: Path,
    state: str,
    age_ms: int = 0,
    pid: int = 4242,
    version: str | None = THIS,  # None: a recorder of 0.6.0 and before, naming none
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    info: dict[str, Any] = {"state": state, "heartbeat_ms": now_ms() - age_ms}
    info["pid"] = pid
    if version is not None:
        info["version"] = version
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


def test_a_dead_recorder_whose_restart_was_refused_is_not_taken_for_alive(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    refused: list[OSError] = []

    def spawning(camera_id: str) -> Any:
        if refused:
            raise refused.pop()
        return spawns(camera_id)

    watchdog = Watchdog("cam1", spawning)
    watchdog.start()
    beat(folder, "recording")  # its last beat, fresh for 15 s more
    clock["now"] = 1000.5
    watchdog.poll()
    spawns.processes[-1].code = -9
    refused.append(OSError("blocked by an antivirus"))
    for moment in (1001, 1002):  # its end seen; the start after the pause refused
        clock["now"] = moment
        watchdog.poll()
    assert watchdog.error == "blocked by an antivirus"
    for moment, started in ((1003, 1), (1005, 2)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started  # after the pause, not 15 s on


class BeatsAsItDies(Process):
    """Killed just after a last beat, which the window read the file before."""

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.folder, self.last_beat = folder, False

    def poll(self) -> int | None:
        if self.code is not None and not self.last_beat:
            self.last_beat = True
            time.sleep(0.002)
            beat(self.folder, "recording")
        return self.code


def test_a_recorder_killed_just_after_a_beat_is_not_taken_for_another(
    folder: Path, clock: dict[str, float]
) -> None:
    made: list[Process] = []

    def spawning(camera_id: str) -> Any:
        made.append(BeatsAsItDies(folder) if not made else Process())
        return made[-1]

    watchdog = Watchdog("cam1", spawning)
    watchdog.start()
    beat(folder, "recording")
    clock["now"] = 1000.5
    watchdog.poll()
    made[-1].code = -9
    for moment, started in ((1001, 1), (1002, 2)):
        clock["now"] = moment
        watchdog.poll()
        assert len(made) == started  # its last beat is its own, not a live one's


def test_a_recorder_whose_end_was_seen_with_its_beat_unread_is_not_taken_for_alive(
    folder: Path, clock: dict[str, float], monkeypatch: pytest.MonkeyPatch
) -> None:
    unread = {"next": False}
    real = launcher.heartbeat

    def read(camera_id: str) -> dict[str, Any] | None:
        if unread["next"]:
            unread["next"] = False
            return None  # cut short by a write in place on a full disk
        return real(camera_id)

    class EndsUnread(Process):
        def poll(self) -> int | None:
            if self.code is not None and not unread.get("seen"):
                unread["seen"] = unread["next"] = True  # the read after it fails
            return self.code

    made: list[Process] = []

    def spawning(camera_id: str) -> Any:
        made.append(EndsUnread() if not made else Process())
        return made[-1]

    monkeypatch.setattr(launcher, "heartbeat", read)
    watchdog = Watchdog("cam1", spawning)
    watchdog.start()
    beat(folder, "recording")
    clock["now"] = 1000.5
    watchdog.poll()
    made[-1].code = -9
    for moment, started in ((1001, 1), (1002, 2)):
        clock["now"] = moment
        watchdog.poll()
        assert len(made) == started  # its own last beat, read once it could be


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


def test_a_recorder_that_dies_while_recording_is_started_again_after_the_pause(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    beat(folder, "recording")  # its last heartbeat, fresh for 15 s more
    spawns.processes[-1].code = -9
    for moment, started in ((1001, 1), (1001.5, 1), (1002, 2)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started


def test_a_recorder_that_found_the_camera_taken_leaves_it_to_the_other(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    beat(folder, "recording")  # the other recorder's
    spawns.processes[-1].code = 3
    for moment in (1001, 1002, 1010):
        clock["now"] = moment
        assert watchdog.poll() == heartbeat("cam1")
    assert len(spawns.processes) == 1


def test_a_recorder_of_another_window_that_beats_is_left_the_camera(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    spawns.processes[-1].code = -9  # this window's recorder dies
    for moment in (1001, 1002):
        clock["now"] = moment
        watchdog.poll()
    assert len(spawns.processes) == 2  # started again
    time.sleep(0.005)
    beat(folder, "recording")  # another window's recorder beats meanwhile
    watchdog.poll()
    spawns.processes[-1].code = 3  # the camera was the other's
    for moment in (1003, 1005, 1010):
        clock["now"] = moment
        assert watchdog.poll() == heartbeat("cam1")
    assert len(spawns.processes) == 2


def test_a_recorder_that_beats_after_this_windows_died_is_left_the_camera(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    beat(folder, "recording")
    clock["now"] = 1000.5
    watchdog.poll()
    spawns.processes[-1].code = -9  # this window's recorder dies
    clock["now"] = 1001
    watchdog.poll()  # its end seen, its last heartbeat noted
    for moment in (1002, 1004, 1010, 1020):
        time.sleep(0.002)
        beat(folder, "recording")  # another window's recorder, beating
        clock["now"] = moment
        watchdog.poll()
    assert len(spawns.processes) == 1  # none started to exit 3 for 15 s


def test_a_start_that_found_the_dead_recorders_lock_still_held_tries_again(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    beat(folder, "recording")
    clock["now"] = 1000.5
    watchdog.poll()
    spawns.processes[-1].code = -9  # killed; its last heartbeat fresh for 15 s more
    for moment, started in ((1001, 1), (1002, 2)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started
    spawns.processes[-1].code = 3  # Windows let go of the dead one's lock late
    for moment, started in ((1003, 2), (1005, 3)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started


def test_a_recorder_that_beat_and_died_between_two_polls_is_started_again(
    folder: Path, clock: dict[str, float]
) -> None:
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    beat(folder, "recording")
    clock["now"] = 1000.5
    watchdog.poll()
    spawns.processes[-1].code = -9  # this window's recorder dies
    for moment, started in ((1001, 1), (1002, 2)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started
    time.sleep(0.002)
    beat(folder, "starting")  # the new one's first word, then its end: no poll saw
    spawns.processes[-1].code = -11  # it run
    for moment, started in ((1003, 2), (1005, 3)):
        clock["now"] = moment
        watchdog.poll()
        assert len(spawns.processes) == started  # not its fresh beat's 15 s later


def test_a_stalled_recorder_that_beats_again_keeps_its_camera(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "recording", age_ms=16_000)  # attached to, it stalled past 15 s
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()  # so another is started
    time.sleep(0.005)
    beat(folder, "recording")  # the stalled one beats again while that one unpacks
    clock["now"] = 1000.5
    watchdog.poll()
    spawns.processes[-1].code = 3  # its lock refused the new one
    for moment in (1001, 1031, 1100):
        clock["now"] = moment
        beat(folder, "recording")
        watchdog.poll()
    assert len(spawns.processes) == 1  # no start every 30 s for ever


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


def test_a_recorder_records_while_its_fresh_heartbeat_says_so() -> None:
    assert launcher.recording({"state": "recording", "heartbeat_ms": now_ms()})
    for state in ("starting", "connecting", "reconnecting", "stopped", "failed"):
        assert not launcher.recording({"state": state, "heartbeat_ms": now_ms()})
    stale = {"state": "recording", "heartbeat_ms": now_ms() - 15_001}
    assert not launcher.recording(stale)  # its recorder died recording
    assert not launcher.recording(None)


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


def lines(path: Path) -> list[str]:
    try:
        return path.read_text().splitlines()
    except OSError:
        return []


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


@pytest.mark.skipif(sys.platform == "win32", reason="os.kill(pid, 0) ends it there")
def test_a_killed_recorder_costs_only_the_time_it_is_down(folder: Path) -> None:
    camera = {"id": "cam1", "connection": "test", "settings": {"fps": 30}}
    session.save({**session.DEFAULTS, "cameras": [camera]})
    watchdog = Watchdog("cam1")
    watchdog.start()
    first = watchdog._process
    assert first is not None
    try:
        wait_for(lambda: (folder / "segments.txt").exists())  # one closed
        wait_for(lambda: len(lines(folder / "current.times")) >= 12)  # 0.4 s open
        killed = now_ms()
        os.kill(first.pid, signal.SIGKILL)
        first.wait(timeout=10)
        wait_for(lambda: watchdog.poll() and watchdog._process is not first, 5)
        restarted = now_ms()
        assert restarted - killed < 3000  # 1 s pause, not a 15 s old heartbeat
        again = watchdog._process
        assert again is not None
        wait_for(lambda: (heartbeat("cam1") or {}).get("pid") == again.pid)
        wait_for(lambda: (heartbeat("cam1") or {}).get("frames", 0) > 10)
        watchdog.stop()
        again.wait(timeout=30)
    finally:
        for process in (first, watchdog._process):
            if process is not None and process.poll() is None:
                process.kill()
    names = (folder / "segments.txt").read_text().split()
    last_before = max(
        int(line.split()[1])
        for name in names
        for line in (folder / f"{name}.times").read_text().splitlines()
        if int(line.split()[1]) < killed
    )
    assert killed - last_before < 500  # the frames written whole before it died
    gaps = (folder / "gaps.txt").read_text().splitlines()
    assert any(line.startswith(f"{last_before} ") for line in gaps)


def test_a_phone_s_clock_exchange_left_out_is_said_whatever_the_state() -> None:
    from app.recorder.launcher import describe

    fresh = int(time.time() * 1000)
    clock = "UDP port 1935 is taken: the phone's frames are placed by their arrival"
    recording = {
        "state": "recording",
        "heartbeat_ms": fresh,
        "frames": 5,
        "clock": clock,
    }
    assert describe(recording) == f"recording, 5 frames; {clock}"
    low = {**recording, "detail": "low disk"}
    assert describe(low) == f"recording, 5 frames, under 2 GB free; {clock}"
    waiting = {"state": "connecting", "heartbeat_ms": fresh, "detail": "waiting for x"}
    assert (
        describe({**waiting, "clock": clock}) == f"connecting: waiting for x; {clock}"
    )
    stopped = {"state": "stopped", "heartbeat_ms": 0, "clock": clock}
    assert describe(stopped) == "stopped"  # nothing placed any more


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


def test_a_phone_catching_up_says_how_far_behind_live_it_is() -> None:
    from app.recorder.launcher import describe

    recording = {"state": "recording", "heartbeat_ms": now_ms(), "frames": 5}
    assert describe({**recording, "behind_ms": 12_345}) == (
        "recording, 5 frames, 12 s behind"
    )
    assert describe({**recording, "behind_ms": 1_999}) == "recording, 5 frames"


def test_a_recorder_of_another_version_is_replaced_once_it_has_stopped(
    folder: Path, clock: dict[str, float]
) -> None:
    # specs/007: an update left the recorder 0.5.0 started at work under 0.6.0.
    beat(folder, "recording", version="0.5.0")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    assert (folder / "stop.request").exists()  # asked to stop
    assert watchdog.replacing == "PhotoFinish 0.5.0"
    watchdog.poll()
    assert not spawns.processes  # it records on until it has stopped
    beat(folder, "stopped", version="0.5.0")
    watchdog.poll()
    assert len(spawns.processes) == 1  # this program's, at once
    assert not watchdog.replacing
    assert not (folder / "stop.request").exists()


def test_a_replacement_is_finished_while_the_window_waits_for_it(
    folder: Path, clock: dict[str, float]
) -> None:
    # A window closed or lost right after it asked the old recorder to stop would
    # leave the camera with none: it waits for it, and starts this one's itself.
    beat(folder, "recording", version="0.5.0")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()

    def pause(seconds: float) -> None:
        clock["now"] += seconds
        beat(folder, "stopped", version="0.5.0")  # it heard the stop meanwhile

    watchdog.finish_replacing(clock["now"] + 5, sleep=pause)
    assert len(spawns.processes) == 1
    assert not watchdog.replacing


def test_a_replacement_not_finished_in_time_is_left_to_the_window_s_polls(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "recording", version="0.5.0")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    waited: list[float] = []

    def pause(seconds: float) -> None:
        waited.append(seconds)
        clock["now"] += seconds
        beat(folder, "recording", version="0.5.0")  # it goes on: a stalled read

    watchdog.finish_replacing(clock["now"] + 1, sleep=pause)
    assert sum(waited) == pytest.approx(1.0)
    assert not spawns.processes
    assert watchdog.replacing == "PhotoFinish 0.5.0"


def test_a_recorder_that_names_no_version_is_an_older_one_replaced(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "recording", version=None)
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    assert watchdog.replacing == "an older PhotoFinish"
    beat(folder, "recording", age_ms=60_000, version=None)  # it hung: gone stale
    watchdog.poll()
    assert len(spawns.processes) == 1


def test_a_recorder_of_this_version_is_attached_to(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "recording")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    watchdog.poll()
    assert not watchdog.replacing
    assert not (folder / "stop.request").exists()
    assert not spawns.processes


def test_a_window_that_cannot_tell_its_version_replaces_no_recorder(
    folder: Path, clock: dict[str, float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "version", lambda: "")
    beat(folder, "recording", version="0.5.0")
    watchdog = Watchdog("cam1", Spawns())
    watchdog.start()
    assert not watchdog.replacing
    assert not (folder / "stop.request").exists()


def test_a_replacement_the_window_stops_meanwhile_starts_none(
    folder: Path, clock: dict[str, float]
) -> None:
    beat(folder, "recording", version="0.5.0")
    spawns = Spawns()
    watchdog = Watchdog("cam1", spawns)
    watchdog.start()
    watchdog.stop()  # the camera removed while the old one stops
    beat(folder, "stopped", version="0.5.0")
    watchdog.poll()
    assert not spawns.processes
    assert not watchdog.replacing


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
