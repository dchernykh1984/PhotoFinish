"""A camera's video as one file (specs/011-video-export).

The recorder keeps a camera's video in one-second pieces, Matroska each, with the
frames' moments in a ``.times`` beside each. An export copies their packets, as
recorded, into MP4 -- the file QuickTime and the phones' players open --, timed by
the moments, each frame once: a packet whose moment its piece does not list was sent
again (specs/007) and written for the frames after it to decode, the piece before
holding it. Where the stream's format changes -- another codec, size or header --
the file ends and ``<name>-2.mp4`` goes on.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

import av

from app.recorder.segments import NAMED, SEGMENTS, frame_times, in_ms

MS = Fraction(1, 1000)


class CancelledError(Exception):
    """The export stopped at the referee's word."""


def pieces(folder: Path) -> list[Path]:
    """A camera's closed pieces, in the order they closed: their videos, each once
    -- a name listed twice is one piece, as the index takes it --, those gone from
    the disk too: told as left out when they are copied."""
    try:  # a byte gone wrong names no piece, and stops nothing
        names = (folder / SEGMENTS).read_text("ascii", errors="replace").split()
    except OSError:
        return []
    named = [n for n in names if NAMED.fullmatch(n)]
    return [folder / f"{n}.mkv" for n in dict.fromkeys(named)]


def has_video(folder: Path) -> bool:
    """Whether a camera has a piece to export: the first listed that is there --
    not every piece looked at, thousands an hour."""
    try:
        names = (folder / SEGMENTS).read_text("ascii", errors="replace").split()
    except OSError:
        return False
    return any((folder / f"{n}.mkv").is_file() for n in names)


def free(path: Path) -> Path:
    """``path``, or ``<stem> (2)<suffix>`` and on when taken: nothing is overwritten."""
    found, n = path, 1
    while found.exists() or found.with_name(found.name + ".part").exists():
        n += 1
        found = path.with_name(f"{path.stem} ({n}){path.suffix}")
    return found


def export(
    folder: Path,
    target: Path,
    progress: Callable[[int, int], None] = lambda done, total: None,
    cancelled: Callable[[], bool] = lambda: False,
    written: list[Path] | None = None,
    skipped: list[Path] | None = None,
) -> list[Path]:
    """The camera's pieces in ``folder`` into ``target`` -- ``<stem>-2`` on beside it
    as the format changes --; the files written, also added to ``written`` as each
    is done. ``progress`` hears of the pieces done of all; ``cancelled`` asked
    between them stops it, the file under way removed (CancelledError), as a file a
    failure leaves is. A piece that cannot be read is skipped, added to
    ``skipped``: the rest of the camera's video still comes."""
    writer = _Writer(target, [] if written is None else written, skipped)
    videos = pieces(folder)
    try:
        for done, video in enumerate(videos):
            if cancelled():
                raise CancelledError
            writer.copy(video)
            progress(done + 1, len(videos))
        writer.finish()
    except BaseException:
        writer.abandon()
        raise
    return writer.mine


class _Writer:
    """The files a camera's pieces are written into, the one under way open."""

    def __init__(self, target: Path, done: list[Path], skipped: list[Path] | None):
        self.target, self.done, self.skipped = target, done, skipped
        self.mine: list[Path] = []  # this export's, of ``done``
        self.out: _Out | None = None
        # The first file's name, free: the parts' after it.
        self.first: Path | None = None
        # A piece skipped or cut short: the next frame written a keyframe.
        self.broken = False

    def copy(self, video: Path) -> None:
        """One piece's listed packets onto the file under way, or a new file when its
        format is another's; a piece that cannot be read, or the rest of it, skipped."""
        try:
            source = av.open(str(video))
        except av.FFmpegError, OSError:
            return self._skip(video)
        with source:
            if not source.streams.video:
                return self._skip(video)
            stream = source.streams.video[0]
            rate = stream.time_base
            time_base = Fraction(rate.numerator, rate.denominator) if rate else MS
            try:
                times = frame_times(video.with_suffix(".times"))
            except (
                OSError,
                ValueError,
            ):  # its times lost or garbled: no moment to place by
                return self._skip(video)
            if self.out is not None and self.out.form != _form(stream):
                self.finish()
            demuxed = source.demux(stream)
            read = 0
            while True:
                try:
                    packet = next(demuxed)
                except StopIteration:
                    return None
                except av.FFmpegError, OSError:
                    # The piece cut short: what was read stays; one read not at all
                    # is told as left out.
                    self.broken = True
                    return None if read else self._skip(video)
                read += 1
                self._add(packet, times, stream, time_base)

    def _add(
        self, packet: av.Packet, times: dict[int, int], stream: Any, time_base: Fraction
    ) -> None:
        if packet.pts is None or packet.dts is None:
            return
        moment = times.get(in_ms(packet.pts, time_base))
        if moment is None:
            return  # sent again: the piece before has it
        if self.out is not None and moment <= self.out.last_moment:
            self.finish()  # the clock set back: a file's time goes on, never back
        if (self.out is None or self.broken) and not packet.is_keyframe:
            return  # a file starts, and goes on after a gap, where it can be decoded
        self.broken = False
        if self.out is None:
            if self.first is None:
                self.first = path = free(self.target)
            else:
                path = free(_part(self.first, len(self.mine) + 1))
            self.out = _Out(path, stream, moment, _form(stream))
        self.out.add(packet, moment, time_base)

    def _skip(self, video: Path) -> None:
        self.broken = True
        if self.skipped is not None:
            self.skipped.append(video)

    def finish(self) -> None:
        if self.out is not None:
            path = self.out.finish()
            self.out = None
            self.mine.append(path)
            self.done.append(path)

    def abandon(self) -> None:
        if self.out is not None:
            out, self.out = self.out, None
            out.abandon()


def _part(target: Path, n: int) -> Path:
    return target if n == 1 else target.with_name(f"{target.stem}-{n}{target.suffix}")


def _form(stream: Any) -> tuple[str, int, int, bytes]:
    """What one file holds one of: the codec, the size and the header."""
    context = stream.codec_context
    return (
        context.name,
        context.width,
        context.height,
        bytes(context.extradata or b""),
    )


class _Out:
    """An MP4 under way, written beside its name and renamed once whole."""

    def __init__(self, path: Path, template: Any, first: int, form: tuple[Any, ...]):
        self.path, self.first, self.form = path, first, form
        self.partial = path.with_name(path.name + ".part")
        self.container = av.open(str(self.partial), "w", format="mp4")
        try:
            when = datetime.datetime.fromtimestamp(first / 1000, datetime.UTC)
            self.container.metadata["creation_time"] = when.isoformat()
            self.stream = self.container.add_stream_from_template(template)
            self.stream.time_base = MS
            if form[0] == "hevc":
                self.stream.codec_tag = "hvc1"  # QuickTime opens H.265 tagged so
        except BaseException:  # a codec MP4 will not hold: no file left half made
            self.abandon()
            raise
        self.last_dts: int | None = None
        self.last_moment = first - 1  # the newest frame's moment written

    def add(self, packet: av.Packet, moment: int, time_base: Fraction) -> None:
        """The packet at its moment; its decode time as far before as it was, never
        going back."""
        pts = moment - self.first
        own_pts, own_dts = packet.pts, packet.dts
        lead = 0
        if own_pts is not None and own_dts is not None:
            lead = in_ms(own_pts - own_dts, time_base)
        dts = pts - lead
        if self.last_dts is not None and dts <= self.last_dts:
            dts = self.last_dts + 1
        self.last_dts = dts
        self.last_moment = moment
        packet.pts, packet.dts = max(pts, dts), dts
        packet.time_base = MS
        packet.stream = self.stream
        self.container.mux(packet)

    def finish(self) -> Path:
        self.container.close()
        self.partial.replace(self.path)
        return self.path

    def abandon(self) -> None:
        try:
            self.container.close()
        finally:
            self.partial.unlink(missing_ok=True)
