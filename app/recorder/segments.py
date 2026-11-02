"""A camera's recording: short Matroska segments, each with a sidecar of frame times.

The segment being written is ``current.mkv`` with ``current.times``, one
``<pts> <Unix ms>`` line a frame, both on disk as they are written. Once both are
closed they are renamed ``<YYYYmmdd-HHMMSS>-<n>``, the times first, so a closed
segment always has its times, and its name is appended to ``segments.txt``: readers
follow that list instead of the folder, which grows by thousands of files an hour. A
segment ends at the first frame a second after its start. Frames are encoded by an
encoder of the segment's own, so it starts with a keyframe (mpeg4, a keyframe every
15 frames, fixed quality 3); a network camera's packets are stored as they came, a
segment starting and ending at the camera's keyframes. A stretch without frames
longer than three frame intervals is appended to ``gaps.txt`` as
``<from ms> <to ms> <reason>``.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterator
from fractions import Fraction
from pathlib import Path
from typing import TextIO

import av
import numpy as np

from app.files import append, write_in_one_step

SEGMENT_MS = 1000  # a segment's first frame is shown once it closes: SC-006's 2 s
CLOSED = "[0-9]*-[0-9]*-[0-9]*"  # a closed segment's name, without its suffix
SEGMENTS = "segments.txt"  # the closed segments' names, in the order they closed
KEYFRAME_SLACK_MS = 100  # a camera's keyframe this much short of a second still cuts
WRITTEN_TOGETHER_S = 2  # a video and its times, closed or recovered in one go
_MS = Fraction(1, 1000)
_GOP = 15
_QUALITY = 3
_QP2LAMBDA = 118  # FFmpeg's scale: quality 3 is global_quality 3 * 118
_AS_IT_COMES = {"flush_packets": "1", "cluster_time_limit": "100"}


class SegmentWriter:
    """Writes one camera's frames into ``folder``; ``close`` ends the open segment."""

    def __init__(
        self,
        folder: Path,
        fps: float,
        segment_ms: int = SEGMENT_MS,
        closed: list[str] | None = None,  # what ``recover`` gave, when it was just run
    ) -> None:
        self.folder, self.fps, self.segment_ms = folder, fps, segment_ms
        closed = recover(folder) if closed is None else closed
        self.segments = len(closed)
        self.frames = 0
        self._last_ms: int | None = None  # this run's newest frame: frames keep order
        # The run before's newest frame: a gap from it noted once, never a frame
        # dropped for it -- a clock set back between runs still records.
        self._before_ms = _last_recorded(folder, closed)
        self.gap_reason = "restart" if self._before_ms is not None else "no frames"
        self._open: _Encoded | _Remuxed | None = None
        self._unlisted: list[str] = []  # closed, the list refused their names so far

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
        """The open segment when it is of ``kind``; else the open one closed, one that
        failed to close finished or its whole frames made a segment, the rest kept
        aside, and a new one begun."""
        opened = self._open if isinstance(self._open, kind) else None
        if opened is None:
            self.close()
            if name := _see_to(self.folder, self.segments + 1):  # a close that failed
                self._closed(name)
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
        name = _name(self.folder, segment.first_ms, self.segments + 1)
        (self.folder / "current.times").replace(self.folder / f"{name}.times")
        (self.folder / "current.mkv").replace(self.folder / f"{name}.mkv")
        self._closed(name)

    def _closed(self, name: str) -> None:
        """``name`` is a closed segment now: counted, and listed with any the list
        refused before."""
        self.segments += 1
        self._unlisted.append(name)  # a list that refuses it now takes it next time
        listed = "".join(f"{closed}\n" for closed in self._unlisted)
        append(self.folder / SEGMENTS, listed.encode("ascii"))
        self._unlisted = []

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
        self.container = _video(folder)
        quality = {"flags": "+qscale", "global_quality": str(_QUALITY * _QP2LAMBDA)}
        rate = Fraction(fps).limit_denominator(1001)
        self.stream = self.container.add_stream("mpeg4", rate=rate, options=quality)
        self.stream.width, self.stream.height = width, height
        self.stream.pix_fmt = "yuv420p"
        self.stream.codec_context.time_base = _MS
        self.stream.time_base = _MS
        self.stream.codec_context.gop_size = _GOP
        self.times: TextIO = _times(folder)

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
        self.container = _video(folder)
        self.stream = self.container.add_stream_from_template(template)
        self.times: TextIO = _times(folder)

    def add(self, packet: av.Packet, pts: int, dts: int, ms: int) -> None:
        packet.pts, packet.dts = pts - self.base, dts - self.base
        pts_ms = _in_ms(pts - self.base, self.time_base)
        packet.stream = self.stream
        self.container.mux(packet)
        self.times.write(f"{pts_ms} {ms}\n")

    def close(self) -> None:
        self.container.close()
        self.times.close()


def _video(folder: Path) -> av.container.OutputContainer:
    """The open segment's video, written out a cluster of at most 0.1 s at a time
    rather than at the segment's end: a killed recorder loses that much at most."""
    return av.open(
        str(folder / "current.mkv"),
        "w",
        format="matroska",
        container_options=_AS_IT_COMES,
    )


def _times(folder: Path) -> TextIO:
    """The open segment's frame times, each line on disk as it is written."""
    return (folder / "current.times").open("w", encoding="ascii", buffering=1)


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
        # read as its readers read it: a byte not ASCII names no segment, stops nothing
        listed = (folder / SEGMENTS).read_bytes().decode("utf-8", "replace").split()
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


def recover(folder: Path) -> list[str]:
    """Every closed segment's name once what a crash left is seen to: a closed one
    it did not list listed, the frames it left whole in ``current.*`` made one, the
    rest kept aside. A recorder does it as it starts, before its camera is back."""
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "recovered.mkv").exists():  # a recovery cut between times and name
        _give_its_name(folder / "recovered.mkv")  # listed with the others below
    closed = _list_missing(folder)
    if name := _see_to(folder, len(closed) + 1):
        append(folder / SEGMENTS, f"{name}\n".encode("ascii"))  # else at the next start
        closed.append(name)
    return closed


def _see_to(folder: Path, n: int) -> str | None:
    """What a crash or a failed close left: a close cut between its renames
    finished, else the whole frames of ``current.*`` made a closed segment numbered
    ``n`` or after, the rest kept aside. The segment's name, for the caller to list."""
    if not (folder / "current.mkv").exists():
        return None  # the usual case, a segment a second: one look, no more
    name = _finish_close(folder) or _recover(folder, n)
    _keep_aside(folder)
    return name


def _finish_close(folder: Path) -> str | None:
    """A close cut between its two renames: the times have their name, the video is
    still ``current.mkv``, and takes the name too when it is theirs. The name, or
    None."""
    if (folder / "current.times").exists():
        return None
    return _give_its_name(folder / "current.mkv")


def _give_its_name(video: Path) -> str | None:
    """``video`` named after the closed times without a video that are its own: the
    same frames, written within seconds of it. Never another's, such as times whose
    video was deleted, sorting after it or not, though a steady camera's segments
    all have the same pts. The name, or None."""
    try:
        with av.open(str(video)) as opened:
            found = sorted(pts for _, pts in _whole(opened))
        made = video.stat().st_mtime
        named = [
            times
            for times in video.parent.glob(f"{CLOSED}.times")
            if not times.with_suffix(".mkv").exists()
            and abs(times.stat().st_mtime - made) <= WRITTEN_TOGETHER_S
            and _frames_of(times) == found
        ]
        if not found or not named:
            return None
        own = min(named, key=lambda times: abs(times.stat().st_mtime - made))
        video.replace(own.with_suffix(".mkv"))
    except OSError, ValueError, IndexError, av.FFmpegError:
        return None
    return own.stem


def _frames_of(times: Path) -> list[int] | None:
    """The pts a closed segment's times list, sorted; None when they cannot be read."""
    try:
        lines = times.read_text(encoding="ascii").splitlines()
        return sorted(int(line.split()[0]) for line in lines)
    except OSError, ValueError, IndexError:
        return None


def _name(folder: Path, first_ms: int, n: int) -> str:
    """A closed segment's name: its first frame's time, a number no other has."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(first_ms / 1000))
    while (folder / f"{stamp}-{n:04d}.mkv").exists():
        n += 1
    return f"{stamp}-{n:04d}"


def _recover(folder: Path, n: int) -> str | None:
    """The frames a crash left whole in ``current.*``, with their times, made a
    closed segment for the caller to list: its name, or None when it holds none.
    What the crash left is kept aside as it was before the copy takes its name, so a
    failure or a crash meanwhile neither shows a frame twice nor loses one."""
    copy = folder / "recovered.mkv"
    try:
        frames = _frame_times(folder / "current.times")
        kept = _copy_whole(folder / "current.mkv", copy, frames)
        if not kept:
            copy.unlink(missing_ok=True)
            return None
        _keep_aside(folder)
        name = _name(folder, kept[0][1], n)
        times = "".join(f"{pts} {ms}\n" for pts, ms in kept)
        write_in_one_step(folder / f"{name}.times", times.encode("ascii"))
        copy.replace(folder / f"{name}.mkv")
    except OSError, ValueError, IndexError, av.FFmpegError:
        with contextlib.suppress(OSError):  # what the crash left is kept aside whole
            copy.unlink(missing_ok=True)
        return None
    return name


def _frame_times(times: Path) -> dict[int, int]:
    """A segment's ``pts -> ms`` as its times file has them, in frame order; a last
    line a kill cut short, its line end missing, is left out, as is one that is not
    two numbers. A pts may be negative: an open GOP's leading frames."""
    found: dict[int, int] = {}
    text = times.read_text(encoding="ascii")
    for line in text.split("\n")[:-1]:  # the last piece: empty, or cut short
        fields = line.split()
        if len(fields) == 2:
            with contextlib.suppress(ValueError):
                found[int(fields[0])] = int(fields[1])
    return found


def _copy_whole(
    left: Path, copy: Path, frames: dict[int, int]
) -> list[tuple[int, int]]:
    """The packets of ``left`` that came whole and have a time, copied as they are
    into a file of their own, which ends as a file should; their ``(pts, ms)``."""
    kept: set[int] = set()
    with av.open(str(left)) as video, av.open(str(copy), "w", format="matroska") as out:
        into = out.add_stream_from_template(video.streams.video[0])
        for packet, pts in _whole(video):
            if pts in frames:
                packet.stream = into
                out.mux(packet)
                kept.add(pts)
    return [(pts, ms) for pts, ms in frames.items() if pts in kept]


def _whole(video: av.container.InputContainer) -> Iterator[tuple[av.Packet, int]]:
    """The video's packets that came whole, each with its pts in ms, up to where a
    crash cut the file, read as any error."""
    source = video.streams.video[0]
    rate = source.time_base
    base = _MS if rate is None else Fraction(rate.numerator, rate.denominator)
    try:
        for packet in video.demux(source):
            if packet.size and packet.pts is not None:
                yield packet, _in_ms(packet.pts, base)
    except av.FFmpegError:
        return  # the cluster the crash cut short: what came before is kept


def _keep_aside(folder: Path) -> None:
    """A segment a crash, or a failed close, left open is not one to show, but what
    it holds is kept: both files under one stamp, the times first, also when a kill
    or a refused rename came between the two last time."""
    times, video = folder / "current.times", folder / "current.mkv"
    stamp = str(time.time_ns() // 1_000_000)
    if video.exists() and not times.exists():
        lone = [
            p
            for p in folder.glob("crashed-*.times")
            if not p.with_suffix(".mkv").exists()
        ]
        if lone:  # its times went aside first: the video joins them
            newest = max(lone, key=lambda p: p.stat().st_mtime_ns)
            stamp = newest.stem.removeprefix("crashed-")
    for left in (times, video):
        if left.exists():
            left.replace(folder / f"crashed-{stamp}{left.suffix}")


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
