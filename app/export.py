"""A camera's video as one file (specs/011-video-export).

The recorder keeps a camera's video in one-second pieces, Matroska each, with the
frames' moments in a ``.times`` beside each. An export copies their packets, as
recorded, into MP4 -- the file QuickTime and the phones' players open --, timed by
the moments, each frame once: a packet whose moment its piece does not list was sent
again (specs/007) and written for the frames after it to decode, the piece before
holding it. Where the stream's format changes -- another codec, size or header --
the file ends and ``<name>-2.mp4`` goes on. The camera's sound -- or another's, its
phone's main lens's -- goes beside the frames, by its moments, the pieces continuous
but for a gap (specs/013).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Iterator, Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

import av

from app import sound
from app.recorder.segments import NAMED, SEGMENTS, frame_times, in_ms
from app.video_index import VideoIndex

MS = Fraction(1, 1000)
CANCELLED = "cancelled"  # what an export of the cameras stopped by the referee tells
STEPS = 1000  # the whole of its progress
FRAME_SLACK_MS = 50  # the sound heard this long after a file's last frame goes in it
# Windows's device names: COM and LPT with a digit, or a superscript one, 1 to 3.
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{d}{n}"
    for d in ("COM", "LPT")
    for n in [*range(10), "\u00b9", "\u00b2", "\u00b3"]
}


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


def file_name(name: str) -> str:
    """A camera's name as a file's on every platform: what a file's name cannot
    hold replaced, and a name Windows keeps for a device -- its part before the
    first dot, spaces after it not counted, whatever follows -- given a mark there."""
    found = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .") or "camera"
    head, dot, rest = found.partition(".")
    if head.rstrip(" ").upper() in RESERVED:
        return f"{head.rstrip(' ')}_{dot}{rest}"
    return found


def has_video(folder: Path) -> bool:
    """Whether a camera has a piece to export: the first listed that is there --
    not every piece looked at, thousands an hour."""
    try:
        names = (folder / SEGMENTS).read_text("ascii", errors="replace").split()
    except OSError:
        return False
    return any((folder / f"{n}.mkv").is_file() for n in names if NAMED.fullmatch(n))


def free(path: Path) -> Path:
    """``path``, or ``<stem> (2)<suffix>`` and on when taken: nothing is overwritten."""
    found, n = path, 1
    while found.exists() or found.with_name(found.name + ".part").exists():
        n += 1
        found = path.with_name(f"{path.stem} ({n}){path.suffix}")
    return found


def export_all(
    jobs: list[tuple[Path, Path]],
    progress: Callable[[int], None] = lambda share: None,
    cancelled: Callable[[], bool] = lambda: False,
    sounds: Mapping[Path, Path] | None = None,
) -> tuple[list[Path], str, int]:
    """Each camera's ``(folder, target)`` exported in turn: the files written --
    those a stop leaves too --, what went wrong -- CANCELLED, or each camera's
    failure, the cameras after it exported still; "" for nothing -- and how many
    pieces could not be read. ``progress`` hears the share done, of STEPS. Each
    camera goes up to the last piece closed as the export began, not as its turn
    comes: the cameras' files end together. ``sounds`` names, by a camera's folder,
    the folder whose sound its file takes: its own without (specs/013)."""
    written: list[Path] = []
    skipped: list[Path] = []
    failed: list[str] = []
    count = len(jobs)
    listed = [pieces(folder) for folder, _ in jobs]
    for n, ((folder, target), videos) in enumerate(zip(jobs, listed, strict=True)):

        def told(done: int, total: int, n: int = n) -> None:
            progress((n * STEPS + done * STEPS // max(total, 1)) // count)

        heard = (sounds or {}).get(folder, folder)
        try:
            export(folder, target, told, cancelled, written, skipped, videos, heard)
        except CancelledError:
            return written, CANCELLED, len(skipped)
        except Exception as failure:
            failed.append(f"{target.stem}: {str(failure) or type(failure).__name__}")
    return written, "; ".join(failed), len(skipped)


def export(
    folder: Path,
    target: Path,
    progress: Callable[[int, int], None] = lambda done, total: None,
    cancelled: Callable[[], bool] = lambda: False,
    written: list[Path] | None = None,
    skipped: list[Path] | None = None,
    videos: list[Path] | None = None,
    heard: Path | None = None,
) -> list[Path]:
    """The camera's pieces in ``folder`` into ``target`` -- ``<stem>-2`` on beside it
    as the format changes --; the files written, also added to ``written`` as each
    is done. ``progress`` hears of the pieces done of all; ``cancelled`` asked
    between them stops it, the file under way removed (CancelledError), as a file a
    failure leaves is. A piece that cannot be read is skipped, added to
    ``skipped``: the rest of the camera's video still comes. The sound of ``heard``
    -- the camera's own folder without -- goes beside the frames."""
    writer = _Writer(target, [] if written is None else written, skipped)
    heard = folder if heard is None else heard
    if _has_sound(heard):  # else hours of pieces are not opened again for none
        writer.heard = VideoIndex(heard)
        writer.heard.refresh()
    if videos is None:  # its pieces as they are now; else as they were listed
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
        self.heard: VideoIndex | None = None  # whose sound the files take (013)

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
        if self.out is not None and packet.is_keyframe and moment <= self.out.newest:
            # The clock set back: a file's time goes on, never back. Told at a keyframe,
            # as a B-frame's moment comes before the frame it follows in decode order.
            self.finish()
        if (self.out is None or self.broken) and not packet.is_keyframe:
            return  # a file starts, and goes on after a gap, where it can be decoded
        self.broken = False
        if self.out is None:
            if self.first is None:
                self.first = path = free(self.target)
            else:
                path = free(_part(self.first, len(self.mine) + 1))
            found = sound.pieces(self.heard, moment) if self.heard else iter(())
            self.out = _Out(path, stream, moment, _form(stream), found)
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


def _has_sound(folder: Path) -> bool:
    """Whether a camera's first piece or its newest keeps sound (013): a microphone
    refused at the start, or lost on the way, is found by one or the other."""
    found = pieces(folder)
    return bool(found) and (sound.has_sound(found[0]) or sound.has_sound(found[-1]))


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
    """An MP4 under way, written beside its name and renamed once whole, the pieces
    of sound ``found`` from its first moment beside its frames."""

    def __init__(
        self,
        path: Path,
        template: Any,
        first: int,
        form: tuple[Any, ...],
        found: Iterator[sound.Piece] | None = None,
    ):
        self.path, self.first, self.form = path, first, form
        self.partial = path.with_name(path.name + ".part")
        self.container = av.open(str(self.partial), "w", format="mp4")
        self.found = iter(()) if found is None else found
        self.piece = next(self.found, None)
        self.audio: Any = None
        self.heard_next: int | None = None  # where the sound written so far ends
        try:
            when = datetime.datetime.fromtimestamp(first / 1000, datetime.UTC)
            self.container.metadata["creation_time"] = when.isoformat()
            self.stream = self.container.add_stream_from_template(template)
            self.stream.time_base = MS
            if form[0] == "hevc":
                self.stream.codec_tag = "hvc1"  # QuickTime opens H.265 tagged so
            if self.piece is not None:
                self.audio = self._sound_stream(self.piece)
        except BaseException:  # a codec MP4 will not hold: no file left half made
            self.abandon()
            raise
        self.last_dts: int | None = None
        self.newest = first - 1  # the newest moment written

    def _sound_stream(self, piece: sound.Piece) -> Any:
        """The file's sound, made from the segment the first piece came from."""
        with av.open(str(piece.path)) as heard:
            made = self.container.add_stream_from_template(heard.streams.audio[0])
        made.time_base = Fraction(1, piece.form.rate)
        return made

    def hear(self, up_to: int) -> None:
        """The pieces of sound at or before ``up_to`` written, each where it was heard
        -- on from the piece before when it is within half a piece of it, so the sound
        runs on --; those before the file's first frame left out."""
        while self.audio is not None and self.piece is not None:
            piece = self.piece
            if piece.ms > up_to:
                return
            self.piece = next(self.found, None)
            if (
                piece.ms < self.first
                or piece.form.rate != self.audio.time_base.denominator
            ):
                continue  # before the file, or of a rate its sound is not
            rate = piece.form.rate
            length = round((piece.end_ms - piece.ms) * rate / 1000)
            frame_size = int(self.audio.codec_context.frame_size or length)
            pts = round((piece.ms - self.first) * rate / 1000)
            if (
                self.heard_next is not None
                and abs(pts - self.heard_next) <= frame_size // 2
            ):
                pts = self.heard_next
            if self.heard_next is not None and pts < self.heard_next:
                continue  # the time goes on, never back
            packet = piece.packet
            packet.pts = packet.dts = pts
            packet.duration = frame_size
            packet.time_base = Fraction(1, rate)
            packet.stream = self.audio
            self.container.mux(packet)
            self.heard_next = pts + frame_size

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
        self.newest = max(self.newest, moment)
        packet.pts, packet.dts = max(pts, dts), dts
        packet.time_base = MS
        packet.stream = self.stream
        self.container.mux(packet)
        self.hear(moment)

    def finish(self) -> Path:
        self.hear(self.newest + FRAME_SLACK_MS)  # the last frame's sound with it
        self.container.close()
        self.partial.replace(self.path)
        return self.path

    def abandon(self) -> None:
        try:
            self.container.close()
        finally:
            self.partial.unlink(missing_ok=True)
