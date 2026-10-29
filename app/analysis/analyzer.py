"""The analyser: a process per camera that indexes where riders are in view.

``<photofinish> --analyzer <camera id>`` reads the camera's closed segments, oldest
first as the recorder lists them in ``segments.txt``, and appends a line for each to
``activity.jsonl``: the stretches with a rider in view -- by motion at five frames a
second, or, with a model chosen, where it sees a person or a bicycle in the zone,
twice a second. A model that cannot be used is reported in ``analyzer.json`` and the
analyser stops. A segment with its line is never analysed again, so a restart goes
on where it stopped. ``analyzer.json`` says how far it has got. It runs below the
recorder in priority and stops when the window that started it is gone: its
standard input closes.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import av

from app import analysis, session
from app.analysis.detector import Detector, ModelError
from app.analysis.motion import WIDTH, Motion, Stretches
from app.analysis.tracks import Ref, Tracker, refine
from app.files import Appended, write_in_one_step
from app.interpolation import Line, finish_line
from app.paths import app_path
from app.recorder import CAMERA_ID, folder_of
from app.recorder.segments import SEGMENTS
from app.video_index import read_times

SAMPLE_MS = 200  # frames looked at for motion: five a second
MODEL_SAMPLE_MS = 500  # and by a model: twice a second
TRIES = 5  # a segment that cannot be read is tried this often, a second apart
ACTIVITY = "activity.jsonl"  # a line a segment, in the order they were analysed
SUGGESTIONS = "suggestions.jsonl"


class Watch(Protocol):
    """How frames are looked at: every frame seen, the samples fed; a sample's
    moment of a rider, or None; the crossings it suggests. What it has seen is
    kept before a segment and put back when the segment fails partway."""

    method: str
    every_ms: int
    suggestions: list[dict[str, Any]]

    def see(self, frame: av.VideoFrame, ref: Ref) -> None: ...

    def feed(self, frame: av.VideoFrame, ref: Ref) -> int | None: ...

    def kept(self) -> Any: ...

    def back_to(self, kept: Any) -> None: ...


class MotionWatch:
    method, every_ms = "motion", SAMPLE_MS

    def __init__(self, motion: Motion) -> None:
        self.motion = motion
        self.suggestions: list[dict[str, Any]] = []  # motion suggests none

    def see(self, frame: av.VideoFrame, ref: Ref) -> None:
        return None

    def feed(self, frame: av.VideoFrame, ref: Ref) -> int | None:
        height = max(round(WIDTH * frame.height / frame.width), 1)
        grey = frame.reformat(width=WIDTH, height=height, format="gray")
        return self.motion.feed(grey.to_ndarray(), ref[2])

    def kept(self) -> Any:
        return copy.deepcopy(self.motion)

    def back_to(self, kept: Any) -> None:
        self.motion = kept


class ModelWatch:
    """Riders in the zone by the model; their crossings of the finish line followed
    and suggested (002 US2)."""

    every_ms = MODEL_SAMPLE_MS

    def __init__(
        self, detector: Detector, zone: analysis.Zone, line: Line, camera_id: str
    ) -> None:
        self.detector, self.zone, self.line = detector, zone, line
        self.camera_id = camera_id
        self.method = f"model:{detector.name}"
        self.tracker = Tracker(line)
        self.frames: list[tuple[av.VideoFrame, Ref]] = []  # since the last sample
        self.suggestions: list[dict[str, Any]] = []

    def see(self, frame: av.VideoFrame, ref: Ref) -> None:
        """Kept as decoded, for the rare crossing that looks at them again: no frame
        is scaled before then."""
        self.frames.append((frame, ref))

    def feed(self, frame: av.VideoFrame, ref: Ref) -> int | None:
        """A rider in the zone: a person or a bicycle overlapping it."""
        boxes = self.detector.riders(frame)
        for found in self.tracker.feed(boxes, ref):
            timed = refine(found, self.frames, self.detector.riders, self.line)
            if timed is not None:
                # Riders abreast may cross at one millisecond: their ids still differ.
                name = f"{self.camera_id}-{timed['ms']}"
                same = sum(s["ms"] == timed["ms"] for s in self.suggestions)
                name += f"-{same + 1}" if same else ""
                self.suggestions.append(
                    {"id": name, "camera": self.camera_id, "model": self.detector.name}
                    | timed
                )
        self.frames = [(f, r) for f, r in self.frames if r[2] >= ref[2]]
        (x0, y0), (x1, y1) = self.zone
        for box in boxes:
            if box.x1 < x1 and box.x2 > x0 and box.y1 < y1 and box.y2 > y0:
                return ref[2]
        return None

    def kept(self) -> Any:
        return copy.deepcopy(self.tracker), list(self.frames), len(self.suggestions)

    def back_to(self, kept: Any) -> None:
        self.tracker, self.frames, suggested = kept
        del self.suggestions[suggested:]


def run(
    camera_id: str,
    stop: Callable[[], bool] | None = None,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Index the camera's segments until ``stop`` -- or, ``once``, until none is
    left; the process's exit code."""
    if not CAMERA_ID.fullmatch(camera_id):
        return 2
    saved = session.load()
    camera = session.camera(saved, camera_id)
    if camera is None:
        return 2
    _lower_priority()
    stop = stop or _window_gone()
    folder = folder_of(camera_id)
    try:
        watch = _watch(camera, analysis.settings(saved)["model"])
    except ModelError as error:
        _progress(folder, "failed", detail=str(error))
        return 2
    sample, listed, done = 0, Appended(folder / SEGMENTS), analysed(folder)
    todo: deque[str] = deque()
    failures: dict[str, int] = {}
    while not stop():
        todo.extend(name for name in listed.new_lines() if name not in done)
        if not todo:
            _progress(folder, "waiting")
            if once:
                return 0
            sleep(1)
            continue
        while todo and not stop():
            name = todo.popleft()
            before = watch.kept()
            try:
                sample = _analyse(folder / f"{name}.mkv", watch, sample)
            except OSError as error:  # held by another process a moment: later
                watch.back_to(before)  # tried again as if never begun
                failures[name] = failures.get(name, 0) + 1
                if failures[name] < TRIES:
                    todo.appendleft(name)  # before the segments after it
                    sleep(1)
                    continue
                _record(folder / f"{name}.mkv", {"version": 1, "error": str(error)})
            done.add(name)
    return 0


def _watch(camera: dict[str, Any], model: str) -> Watch:
    """By the model chosen, or by motion without one."""
    zone, line = analysis.zone(camera), finish_line(camera.get("finish_line"))
    if model:
        return ModelWatch(Detector(app_path(model)), zone, line, str(camera["id"]))
    return MotionWatch(Motion(zone, line))


def analysed(folder: Path) -> set[str]:
    """The segments with their activity written: never analysed twice."""
    found = set()
    for line in Appended(folder / ACTIVITY).new_lines():
        try:
            found.add(str(json.loads(line)["segment"]))
        except ValueError, KeyError, TypeError:
            continue
    return found


def _analyse(segment: Path, watch: Watch, sample: int) -> int:
    """One segment's stretches recorded; the next moment to look at. A segment that
    cannot be read now raises OSError; one whose content cannot be read is noted."""
    pairs = read_times(segment)
    if pairs is None:
        raise OSError(f"the frame times of {segment.name} cannot be read")
    times = dict(pairs.tolist())
    stretches, seen = Stretches(), []
    try:
        with av.open(str(segment)) as container:
            for frame in container.decode(video=0):
                pts = frame.pts if frame.pts is not None else -1
                ms = times.get(pts)
                if ms is None:
                    continue
                ref = (segment.name, pts, ms)
                watch.see(frame, ref)
                if ms < sample:
                    continue
                stretches.add(ms, watch.feed(frame, ref))
                seen.append(ms)
                sample = ms + watch.every_ms
    except OSError:
        raise  # held a moment, or not there: tried again
    except av.FFmpegError as error:  # what is in it cannot be read: noted, passed
        _record(segment, {"version": 1, "error": str(error)})
        return sample
    activity = {
        "segment": segment.stem,
        "version": 1,
        "method": watch.method,
        "first_ms": min(seen, default=None),
        "last_ms": max(seen, default=None),
        "stretches": stretches.found,
    }
    _suggest(segment.parent, watch.suggestions)
    watch.suggestions.clear()
    _record(segment, activity)
    _progress(segment.parent, "analysing", max(times.values(), default=None))
    return sample


def _record(segment: Path, activity: dict[str, Any]) -> None:
    """A segment's activity appended: the list the window follows."""
    line = json.dumps({"segment": segment.stem} | activity) + "\n"
    with (segment.parent / ACTIVITY).open("a", encoding="ascii") as f:
        f.write(line)


def _suggest(folder: Path, suggestions: list[dict[str, Any]]) -> None:
    """Crossings suggested, appended for the window to list."""
    if not suggestions:
        return
    with (folder / SUGGESTIONS).open("a", encoding="ascii") as f:
        f.writelines(json.dumps(s) + "\n" for s in suggestions)


def _progress(
    folder: Path, state: str, done_ms: int | None = None, detail: str = ""
) -> None:
    path = folder / "analyzer.json"
    try:
        before = json.loads(path.read_text(encoding="ascii"))
    except OSError, ValueError:
        before = {}
    info = {
        "pid": os.getpid(),
        "heartbeat_ms": time.time_ns() // 1_000_000,
        "state": state,
        "detail": detail,
        "done_ms": done_ms if done_ms is not None else before.get("done_ms"),
    }
    _write(path, info)


def _write(path: Path, data: dict[str, Any]) -> None:
    try:
        write_in_one_step(path, (json.dumps(data) + "\n").encode("ascii"))
    except OSError:
        return  # a full disk, or a reader holding it for long: the next one


def _window_gone() -> Callable[[], bool]:
    """True once the window that started this process is gone: the standard input
    it holds open is closed then."""
    gone = threading.Event()

    def watch() -> None:
        stream = sys.stdin
        if stream is None:
            return  # nothing to tell by: run until stopped
        try:
            while stream.buffer.read(1024):
                pass
        except OSError, ValueError:
            pass
        gone.set()

    threading.Thread(target=watch, daemon=True).start()
    return gone.is_set


def _lower_priority() -> None:
    """Below the recorder: recording never waits for the analysis."""
    try:
        if sys.platform == "win32":
            import ctypes

            kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000)  # below normal
        else:
            os.nice(10)
    except OSError, AttributeError:  # pragma: no cover - a system that refuses
        pass
