"""The analyser: a process per camera that indexes where riders are in view.

``<photofinish> --analyzer <camera id>`` reads the camera's closed segments, oldest
first, and writes beside each one ``<segment>.activity.json``: the stretches with a
rider in view -- by motion at five frames a second, or, with a model chosen, where
it sees a person or a bicycle in the zone, twice a second. A model that cannot be
used is reported in ``analyzer.json`` and the analyser stops. A segment with its
file is never analysed again, so a restart goes on where it stopped.
``analyzer.json`` says how far it has got. It runs below the recorder in priority
and stops when the window that started it is gone: its standard input closes.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import av

from app import analysis, session
from app.analysis.detector import Detector, ModelError
from app.analysis.motion import WIDTH, Motion, Stretches
from app.analysis.tracks import Ref, Tracker, refine
from app.interpolation import Line, finish_line
from app.paths import app_path
from app.recorder import CAMERA_ID, folder_of
from app.recorder.segments import CLOSED

SAMPLE_MS = 200  # frames looked at for motion: five a second
MODEL_SAMPLE_MS = 500  # and by a model: twice a second
ACTIVITY = ".activity.json"
SUGGESTIONS = "suggestions.jsonl"


class Watch(Protocol):
    """How frames are looked at: every frame seen, the samples fed; a sample's
    moment of a rider, or None; the crossings it suggests."""

    method: str
    every_ms: int
    suggestions: list[dict[str, Any]]

    def see(self, frame: av.VideoFrame, ref: Ref) -> None: ...

    def feed(self, frame: av.VideoFrame, ref: Ref) -> int | None: ...


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
        """Kept, as small as the model looks at it, to find a crossing's frames."""
        width = min(frame.width, self.detector.width)
        height = max(round(width * frame.height / frame.width), 1)
        self.frames.append((frame.reformat(width=width, height=height), ref))

    def feed(self, frame: av.VideoFrame, ref: Ref) -> int | None:
        """A rider in the zone: a person or a bicycle overlapping it."""
        boxes = self.detector.riders(frame)
        for found in self.tracker.feed(boxes, ref):
            timed = refine(found, self.frames, self.detector.riders, self.line)
            if timed is not None:
                name = f"{self.camera_id}-{timed['ms']}"
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
    camera = session.camera(session.load(), camera_id)
    if camera is None:
        return 2
    _lower_priority()
    stop = stop or _window_gone()
    folder = folder_of(camera_id)
    try:
        watch = _watch(camera, analysis.settings(session.load())["model"])
    except ModelError as error:
        _progress(folder, "failed", detail=str(error))
        return 2
    sample = 0
    while not stop():
        todo = unanalysed(folder)
        if not todo:
            _progress(folder, "waiting")
            if once:
                return 0
            sleep(1)
            continue
        for segment in todo:
            if stop():
                break
            sample = _analyse(segment, watch, sample)
    return 0


def _watch(camera: dict[str, Any], model: str) -> Watch:
    """By the model chosen, or by motion without one."""
    zone, line = analysis.zone(camera), finish_line(camera.get("finish_line"))
    if model:
        return ModelWatch(Detector(app_path(model)), zone, line, str(camera["id"]))
    return MotionWatch(Motion(zone, line))


def unanalysed(folder: Path) -> list[Path]:
    """The closed segments without their activity, oldest first."""
    return sorted(
        path
        for path in folder.glob(f"{CLOSED}.mkv")
        if not path.with_suffix(ACTIVITY).exists()
    )


def _analyse(segment: Path, watch: Watch, sample: int) -> int:
    """One segment's stretches written beside it; the next moment to look at."""
    times = _times(segment)
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
    except (OSError, av.FFmpegError) as error:
        _write(segment.with_suffix(ACTIVITY), {"version": 1, "error": str(error)})
        return sample
    activity = {
        "version": 1,
        "method": watch.method,
        "first_ms": min(seen, default=None),
        "last_ms": max(seen, default=None),
        "stretches": stretches.found,
    }
    _suggest(segment.parent, watch.suggestions)
    watch.suggestions.clear()
    _write(segment.with_suffix(ACTIVITY), activity)
    _progress(segment.parent, "analysing", max(times.values(), default=None))
    return sample


def _suggest(folder: Path, suggestions: list[dict[str, Any]]) -> None:
    """Crossings suggested, appended for the window to list."""
    if not suggestions:
        return
    with (folder / SUGGESTIONS).open("a", encoding="ascii") as f:
        f.writelines(json.dumps(s) + "\n" for s in suggestions)


def _times(segment: Path) -> dict[int, int]:
    try:
        tokens = segment.with_suffix(".times").read_text(encoding="ascii").split()
    except OSError:
        return {}
    return {
        int(pts): int(ms) for pts, ms in zip(tokens[::2], tokens[1::2], strict=False)
    }


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
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data) + "\n", encoding="ascii")
        tmp.replace(path)
    except OSError:
        return  # a full disk or a reader holding it: the next one


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
