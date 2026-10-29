"""A camera's recording: short Matroska segments, each with a sidecar of frame times.

The segment being written is ``current.mkv`` with ``current.times``, one
``<pts> <Unix ms>`` line a frame. Once both are closed they are renamed
``<YYYYmmdd-HHMMSS>-<n>``, the times first, so a closed segment always has its
times, and its name is appended to ``segments.txt``: readers follow that list instead
of the folder, which grows by thousands of files an hour. A segment ends at the first
frame a second after its start. Frames are
encoded by an encoder of the segment's own, so it starts with a keyframe (mpeg4, a
keyframe every 15 frames, fixed quality 3); a network camera's packets are stored as
they came, a segment starting and ending at the camera's keyframes. A stretch
without frames longer than three frame intervals is appended to ``gaps.txt`` as
``<from ms> <to ms> <reason>``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import TextIO

import av
import numpy as np

from app.files import append

SEGMENT_MS = 1000  # a segment's first frame is shown once it closes: SC-006's 2 s
CLOSED = "[0-9]*-[0-9]*-[0-9]*"  # a closed segment's name, without its suffix
SEGMENTS = "segments.txt"  # the closed segments' names, in the order they closed
KEYFRAME_SLACK_MS = 100  # a camera's keyframe this much short of a second still cuts
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
        closed = _list_missing(folder)
        self.segments = len(closed)
        self.frames = 0
        self._last_ms: int | None = None  # this run's newest frame: frames keep order
        # The run before's newest frame: a gap from it noted once, never a frame
        # dropped for it -- a clock set back between runs still records.
        self._before_ms = _last_recorded(folder, closed)
        self.gap_reason = "restart" if self._before_ms is not None else "no frames"
        self._open: _Encoded | _Remuxed | None = None

    def write(self, image: np.ndarray | av.VideoFrame, ms: int) -> None:
        """A frame taken at ``ms``; frames must come in time order."""
        if self._last_ms is not None and ms <= self._last_ms:
            return  # a frame out of order cannot be muxed; the next one can
        self._next(ms, cut=True)
        opened = self._segment(
            _Encoded, lambda: _Encoded(self.folder, image, ms, self.fps)
        )
        opened.add(image, ms)
        self.frames += 1

    def write_packet(self, packet: av.Packet, ms: int) -> None:
        """A packet of a network camera, its frame taken at ``ms``. A segment starts
        at a keyframe; packets before the first are of no use and are dropped."""
        if packet.pts is None or packet.dts is None or packet.stream is None:
            return  # nothing to place it by
        if not isinstance(self._open, _Remuxed) and not packet.is_keyframe:
            return
        # A camera's keyframes a second apart cut each one, a moment early or late.
        self._next(ms, cut=packet.is_keyframe, slack=KEYFRAME_SLACK_MS)
        stream = packet.stream
        opened = self._segment(
            _Remuxed, lambda: _Remuxed(self.folder, packet, stream, ms)
        )
        opened.add(packet, packet.pts, packet.dts, ms)
        self.frames += 1

    def _segment[T: (_Encoded, _Remuxed)](
        self, kind: type[T], begun: Callable[[], T]
    ) -> T:
        """The open segment when it is of ``kind``; else the open one closed, what one
        that failed to close left kept aside, and a new one begun."""
        opened = self._open if isinstance(self._open, kind) else None
        if opened is None:
            self.close()
            _keep_aside(self.folder)
            opened = begun()
            self._open = opened
        return opened

    def _next(self, ms: int, cut: bool, slack: int = 0) -> None:
        """A gap before ``ms`` noted; the open segment closed when it is long enough
        and ``ms`` may start the next."""
        last = self._last_ms if self._last_ms is not None else self._before_ms
        self._before_ms = None
        if last is not None and ms - last > 3 * 1000 / self.fps:
            self._gap(last, ms)
        if (
            cut
            and self._open is not None
            and ms - self._open.first_ms >= self.segment_ms - slack
        ):
            self.close()
        self._last_ms = max(ms, self._last_ms or ms)

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
        append(self.folder / SEGMENTS, f"{name}\n".encode("ascii"))

    def _gap(self, start: int, end: int) -> None:
        line = f"{start} {end} {self.gap_reason}\n"
        append(self.folder / "gaps.txt", line.encode("ascii"))
        self.gap_reason = "no frames"


class _Encoded:
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


class _Remuxed:
    """A camera's packets stored as they came, from its first keyframe on."""

    def __init__(
        self, folder: Path, first: av.Packet, template: av.stream.Stream, ms: int
    ) -> None:
        self.first_ms = ms
        self.base = first.dts or 0  # timestamps start at 0 in each segment
        rate = first.time_base
        self.time_base = Fraction(rate.numerator, rate.denominator)
        self.container = av.open(str(folder / "current.mkv"), "w", format="matroska")
        self.stream = self.container.add_stream_from_template(template)
        self.times: TextIO = (folder / "current.times").open("w", encoding="ascii")

    def add(self, packet: av.Packet, pts: int, dts: int, ms: int) -> None:
        packet.pts, packet.dts = pts - self.base, dts - self.base
        pts_ms = _in_ms(pts - self.base, self.time_base)
        packet.stream = self.stream
        self.container.mux(packet)
        self.times.write(f"{pts_ms} {ms}\n")

    def close(self) -> None:
        self.container.close()
        self.times.close()


def _in_ms(value: int, time_base: Fraction) -> int:
    """``value`` in ``time_base`` as whole milliseconds, rounded as the muxer rounds."""
    scaled = value * time_base * 1000
    return (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)


def _size(image: np.ndarray | av.VideoFrame) -> tuple[int, int]:
    if isinstance(image, av.VideoFrame):
        return image.height, image.width
    return image.shape[0], image.shape[1]


def _list_missing(folder: Path) -> list[str]:
    """Every closed segment's name, the list completed with any a crash closed but
    did not list; once, when a recorder starts."""
    try:
        listed = (folder / SEGMENTS).read_text(encoding="ascii").split()
    except OSError:
        listed = []
    known = set(listed)
    missing = sorted(
        path.stem
        for path in folder.glob(f"{CLOSED}.mkv")
        if path.stem not in known and path.with_suffix(".times").exists()
    )
    if missing:
        append(folder / SEGMENTS, "".join(f"{n}\n" for n in missing).encode("ascii"))
    return listed + missing


def _keep_aside(folder: Path) -> None:
    """A segment a crash, or a failed close, left open is not one to show, but what
    it holds is kept."""
    stamp = time.time_ns() // 1_000_000
    for suffix in (".times", ".mkv"):
        left = folder / f"current{suffix}"
        if left.exists():
            left.replace(folder / f"crashed-{stamp}{suffix}")


def _last_recorded(folder: Path, closed: list[str]) -> int | None:
    """The time of the run before's newest frame: the last of the segment closed
    last. Taken from the list, not by looking at every segment of a long day."""
    for name in reversed(
        closed
    ):  # a name a kill cut short has no times: the one before
        try:
            found = (folder / f"{name}.times").read_text(encoding="ascii").split()
            return int(found[-1]) if found else None
        except OSError, ValueError:
            continue
    return None
