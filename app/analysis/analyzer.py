"""The analyser: a process per camera that indexes where riders are in view.

``<photofinish> --analyzer <camera id>`` reads the camera's closed segments, oldest
first, at five frames a second, and writes beside each one
``<segment>.activity.json``: the stretches with a rider in view. A segment with its
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
from typing import Any

import av

from app import analysis, session
from app.analysis.motion import WIDTH, Motion, Stretches
from app.interpolation import finish_line
from app.recorder import CAMERA_ID, folder_of
from app.recorder.segments import CLOSED

SAMPLE_MS = 200  # frames looked at: five a second
ACTIVITY = ".activity.json"


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
    line = finish_line(camera.get("finish_line"))
    motion, sample = Motion(analysis.zone(camera), line), 0
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
            sample = _analyse(segment, motion, sample)
    return 0


def unanalysed(folder: Path) -> list[Path]:
    """The closed segments without their activity, oldest first."""
    return sorted(
        path
        for path in folder.glob(f"{CLOSED}.mkv")
        if not path.with_suffix(ACTIVITY).exists()
    )


def _analyse(segment: Path, motion: Motion, sample: int) -> int:
    """One segment's stretches written beside it; the next moment to look at."""
    times = _times(segment)
    stretches, seen = Stretches(), []
    try:
        with av.open(str(segment)) as container:
            for frame in container.decode(video=0):
                ms = times.get(frame.pts if frame.pts is not None else -1)
                if ms is None or ms < sample:
                    continue
                height = max(round(WIDTH * frame.height / frame.width), 1)
                grey = frame.reformat(width=WIDTH, height=height, format="gray")
                stretches.add(ms, motion.feed(grey.to_ndarray(), ms))
                seen.append(ms)
                sample = ms + SAMPLE_MS
    except (OSError, av.FFmpegError) as error:
        _write(segment.with_suffix(ACTIVITY), {"version": 1, "error": str(error)})
        return sample
    activity = {
        "version": 1,
        "method": "motion",
        "first_ms": min(seen, default=None),
        "last_ms": max(seen, default=None),
        "stretches": stretches.found,
    }
    _write(segment.with_suffix(ACTIVITY), activity)
    _progress(segment.parent, "analysing", max(times.values(), default=None))
    return sample


def _times(segment: Path) -> dict[int, int]:
    try:
        tokens = segment.with_suffix(".times").read_text(encoding="ascii").split()
    except OSError:
        return {}
    return {
        int(pts): int(ms) for pts, ms in zip(tokens[::2], tokens[1::2], strict=False)
    }


def _progress(folder: Path, state: str, done_ms: int | None = None) -> None:
    path = folder / "analyzer.json"
    try:
        before = json.loads(path.read_text(encoding="ascii"))
    except OSError, ValueError:
        before = {}
    info = {
        "pid": os.getpid(),
        "heartbeat_ms": time.time_ns() // 1_000_000,
        "state": state,
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
