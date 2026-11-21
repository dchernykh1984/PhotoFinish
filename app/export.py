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

from app.recorder.segments import SEGMENTS, frame_times, in_ms

MS = Fraction(1, 1000)


class CancelledError(Exception):
    """The export stopped at the referee's word."""


def pieces(folder: Path) -> list[Path]:
    """A camera's closed pieces, in the order they closed: their videos."""
    try:
        names = (folder / SEGMENTS).read_text(encoding="ascii").split()
    except OSError:
        return []
    return [folder / f"{n}.mkv" for n in names if (folder / f"{n}.mkv").is_file()]


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
) -> list[Path]:
    """The camera's pieces in ``folder`` into ``target`` -- ``<stem>-2`` on beside it
    as the format changes --; the files written. ``progress`` hears of the pieces
    done of all; ``cancelled`` asked between them stops it, the file under way
    removed (CancelledError)."""
    videos = pieces(folder)
    written: list[Path] = []
    out: _Out | None = None
    try:
        for done, video in enumerate(videos):
            if cancelled():
                raise CancelledError
            out = _copy(video, out, target, written)
            progress(done + 1, len(videos))
        if out is not None:
            written.append(out.finish())
            out = None
    except BaseException:
        if out is not None:
            out.abandon()
        raise
    return written


def _copy(
    video: Path, out: _Out | None, target: Path, written: list[Path]
) -> _Out | None:
    """One piece's listed packets onto ``out``, or a new file when its format is
    another's; the file it leaves open."""
    times = frame_times(video.with_suffix(".times"))
    with av.open(str(video)) as source:
        stream = source.streams.video[0]
        rate = stream.time_base
        time_base = Fraction(rate.numerator, rate.denominator) if rate else MS
        form = _form(stream)
        if out is not None and out.form != form:
            written.append(out.finish())
            out = None
        for packet in source.demux(stream):
            if packet.pts is None or packet.dts is None:
                continue
            moment = times.get(in_ms(packet.pts, time_base))
            if moment is None:
                continue  # sent again: the piece before has it
            if out is None:
                if not packet.is_keyframe:
                    continue  # a file starts where it can be decoded
                path = free(_part(target, len(written) + 1))
                out = _Out(path, stream, moment, form)
            out.add(packet, moment, time_base)
    return out


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
        when = datetime.datetime.fromtimestamp(first / 1000, datetime.UTC)
        self.container.metadata["creation_time"] = when.isoformat()
        self.stream = self.container.add_stream_from_template(template)
        self.stream.time_base = MS
        if form[0] == "hevc":
            self.stream.codec_tag = "hvc1"  # QuickTime opens H.265 tagged so
        self.last_dts: int | None = None

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
