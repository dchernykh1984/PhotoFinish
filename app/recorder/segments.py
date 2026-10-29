"""A camera's recording: short Matroska segments, each with a sidecar of frame times.

The segment being written is ``current.mkv`` with ``current.times``, one
``<pts> <Unix ms>`` line a frame. Once both are closed they are renamed
``<YYYYmmdd-HHMMSS>-<n>``, the times first, so a closed segment always has its
times. A segment ends at the first frame two seconds after its start; each has an
encoder of its own, so it starts with a keyframe (mpeg4, a keyframe every 15 frames,
fixed quality 3). A stretch without frames longer than three frame intervals is
appended to ``gaps.txt`` as ``<from ms> <to ms> <reason>``.
"""

from __future__ import annotations

import time
from fractions import Fraction
from pathlib import Path
from typing import TextIO

import av
import numpy as np

SEGMENT_MS = 2000
CLOSED = "[0-9]*-[0-9]*-[0-9]*"  # a closed segment's name, without its suffix
_MS = Fraction(1, 1000)
_GOP = 15
_QUALITY = 3
_QP2LAMBDA = 118  # FFmpeg's scale: quality 3 is global_quality 3 * 118


class SegmentWriter:
    """Writes one camera's frames into ``folder``; ``close`` ends the open segment."""

    def __init__(self, folder: Path, fps: float, segment_ms: int = SEGMENT_MS) -> None:
        self.folder, self.fps, self.segment_ms = folder, fps, segment_ms
        folder.mkdir(parents=True, exist_ok=True)
        _keep_aside(folder)
        self.segments = sum(1 for _ in folder.glob(f"{CLOSED}.mkv"))
        self.frames = 0
        self._last_ms = _last_recorded(folder)
        self.gap_reason = "restart" if self._last_ms is not None else "no frames"
        self._open: _Segment | None = None

    def write(self, image: np.ndarray | av.VideoFrame, ms: int) -> None:
        """A frame taken at ``ms``; frames must come in time order."""
        if self._last_ms is not None:
            if ms <= self._last_ms:
                return  # a frame out of order cannot be muxed; the next one can
            if ms - self._last_ms > 3 * 1000 / self.fps:
                self._gap(self._last_ms, ms)
        if self._open is not None and ms - self._open.first_ms >= self.segment_ms:
            self.close()
        if self._open is None:
            self._open = _Segment(self.folder, image, ms, self.fps)
        self._open.add(image, ms)
        self._last_ms = ms
        self.frames += 1

    def close(self) -> None:
        """End the open segment: both files closed, then renamed, the times first."""
        if self._open is None:
            return
        segment, self._open = self._open, None
        segment.close()
        self.segments += 1
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(segment.first_ms / 1000))
        n = self.segments
        while (self.folder / f"{stamp}-{n:04d}.mkv").exists():
            n += 1
        name = f"{stamp}-{n:04d}"
        (self.folder / "current.times").replace(self.folder / f"{name}.times")
        (self.folder / "current.mkv").replace(self.folder / f"{name}.mkv")

    def _gap(self, start: int, end: int) -> None:
        with (self.folder / "gaps.txt").open("a", encoding="ascii") as f:
            f.write(f"{start} {end} {self.gap_reason}\n")
        self.gap_reason = "no frames"


class _Segment:
    def __init__(
        self, folder: Path, first: np.ndarray | av.VideoFrame, ms: int, fps: float
    ) -> None:
        self.first_ms = ms
        height, width = _size(first)
        self.container = av.open(str(folder / "current.mkv"), "w", format="matroska")
        quality = {"flags": "+qscale", "global_quality": str(_QUALITY * _QP2LAMBDA)}
        rate = Fraction(fps).limit_denominator(1001)
        self.stream = self.container.add_stream("mpeg4", rate=rate, options=quality)
        self.stream.width, self.stream.height = width, height
        self.stream.pix_fmt = "yuv420p"
        self.stream.codec_context.time_base = _MS
        self.stream.time_base = _MS
        self.stream.codec_context.gop_size = _GOP
        self.times: TextIO = (folder / "current.times").open("w", encoding="ascii")

    def add(self, image: np.ndarray | av.VideoFrame, ms: int) -> None:
        if isinstance(image, av.VideoFrame):
            frame = image
        else:
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        frame.pts, frame.time_base = ms - self.first_ms, _MS
        for packet in self.stream.encode(frame):
            self.container.mux(packet)
        self.times.write(f"{frame.pts} {ms}\n")

    def close(self) -> None:
        for packet in self.stream.encode(None):
            self.container.mux(packet)
        self.container.close()
        self.times.close()


def _size(image: np.ndarray | av.VideoFrame) -> tuple[int, int]:
    if isinstance(image, av.VideoFrame):
        return image.height, image.width
    return image.shape[0], image.shape[1]


def _keep_aside(folder: Path) -> None:
    """A segment a crash left open is not one to show, but what it holds is kept."""
    stamp = time.time_ns() // 1_000_000
    for suffix in (".times", ".mkv"):
        left = folder / f"current{suffix}"
        if left.exists():
            left.replace(folder / f"crashed-{stamp}{suffix}")


def _last_recorded(folder: Path) -> int | None:
    """The time of the newest frame in a closed segment of ``folder``, if any."""
    times = list(folder.glob(f"{CLOSED}.times"))
    if not times:
        return None
    newest = max(times, key=lambda path: path.stat().st_mtime_ns)
    lines = newest.read_text(encoding="ascii").split()
    return int(lines[-1]) if lines else None
