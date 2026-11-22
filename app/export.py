"""A camera's video as one file (specs/011-video-export).

The recorder keeps a camera's video in one-second pieces, Matroska each, with the
frames' moments in a ``.times`` beside each. An export copies their packets, as
recorded, into MP4 -- the file QuickTime and the phones' players open --, timed by
the moments, each frame once: a packet whose moment its piece does not list was sent
again (specs/007) and written for the frames after it to decode, the piece before
holding it. Where the stream's format changes -- another codec, size or header --
the file ends and ``<name>-2.mp4`` goes on. The phone's sound -- the camera's own,
and its phone's other lenses' where one of them kept it -- goes beside the frames, by
its moments, the pieces continuous but for a gap (specs/013).
"""

from __future__ import annotations

import dataclasses
import datetime
import functools
import heapq
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import numpy as np

from app import sound
from app.files import retried
from app.recorder.segments import NAMED, SEGMENTS, frame_times, in_ms
from app.video_index import VideoIndex

MS = Fraction(1, 1000)
CANCELLED = "cancelled"  # what an export of the cameras stopped by the referee tells
STEPS = 1000  # the whole of its progress
FRAME_SLACK_MS = 50  # the sound heard this long after a file's last frame goes in it
HELD_S = 0.1  # a piece whose times are held a moment, read again this much later
HELD_TRIES = 5  # and so often: times a crash garbled hold each export no longer
SILENCE_ASKS = 1000  # silent pieces a gap is filled with between asks for Cancel
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
    sounds: Mapping[Path, Sequence[tuple[Path, int]]] | None = None,
) -> tuple[list[Path], str, int]:
    """Each camera's ``(folder, target)`` exported in turn: the files written --
    those a stop leaves too --, what went wrong -- CANCELLED, or each camera's
    failure, the cameras after it exported still; "" for nothing -- and how many
    pieces could not be read. ``progress`` hears the share done, of STEPS. Each
    camera goes up to the last piece closed as the export began, not as its turn
    comes: the cameras' files end together. ``sounds`` names, by a camera's folder,
    the folders whose sound its file takes -- its own without -- each with the ms
    that sound goes later than its own moments: the two cameras' offsets apart
    (specs/013)."""
    written: list[Path] = []
    skipped: list[Path] = []
    failed: list[str] = []
    count = len(jobs)
    listed = [pieces(folder) for folder, _ in jobs]
    indexes: dict[Path, VideoIndex] = {}  # a sound's pieces listed once for all
    for n, ((folder, target), videos) in enumerate(zip(jobs, listed, strict=True)):

        def told(done: int, total: int, n: int = n) -> None:
            progress((n * STEPS + done * STEPS // max(total, 1)) // count)

        heard = list((sounds or {}).get(folder, [(folder, 0)]))
        try:
            export(
                folder,
                target,
                told,
                cancelled,
                written,
                skipped,
                videos,
                heard,
                indexes,
            )
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
    heard: Sequence[tuple[Path, int]] | None = None,
    indexes: dict[Path, VideoIndex] | None = None,
) -> list[Path]:
    """The camera's pieces in ``folder`` into ``target`` -- ``<stem>-2`` on beside it
    as the format changes --; the files written, also added to ``written`` as each
    is done. ``progress`` hears of the pieces done of all; ``cancelled`` asked
    between them stops it, the file under way removed (CancelledError), as a file a
    failure leaves is. A piece that cannot be read is skipped, added to
    ``skipped``: the rest of the camera's video still comes. The sound of each of
    ``heard``'s folders -- the camera's own without -- goes beside the frames, as
    many ms later than its own moments as it says: a phone's, whichever of its
    lenses kept it at each moment."""
    writer = _Writer(target, [] if written is None else written, skipped)
    writer.cancelled = cancelled  # asked as its sound is looked for too
    known = {} if indexes is None else indexes  # listed once for a phone's lenses
    for source, shift in [(folder, 0)] if heard is None else heard:
        if has_sound(source):  # else hours of pieces are not opened again for none
            if source not in known:
                known[source] = _listed(source, cancelled)
            writer.sounds.append((known[source], shift))
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
        # Whose sound the files take, each how much later than its own moments (013).
        self.sounds: list[tuple[VideoIndex, int]] = []
        self.cancelled: Callable[[], bool] = lambda: False

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
            found = _merged(self.sounds, moment, self.cancelled)
            self.out = _Out(path, stream, moment, _form(stream), found, self.cancelled)
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


def _listed(folder: Path, cancelled: Callable[[], bool]) -> VideoIndex:
    """A camera's recording as its sound is read from: a piece whose times are held
    by their writer a moment read again, as the window's polls would, before it is
    given up -- never its sound left out for that moment."""
    index = VideoIndex(folder)
    index.refresh()
    for _ in range(HELD_TRIES):
        if not index.pending or cancelled():
            break
        time.sleep(HELD_S)
        index.refresh()
    return index


def _merged(
    sounds: list[tuple[VideoIndex, int]], moment: int, cancelled: Callable[[], bool]
) -> Iterator[sound.Piece]:
    """The pieces of each sound from ``moment``, on the file's moments -- each its
    ms later --, in the order heard: a phone's sound, whichever lens kept it then."""
    return heapq.merge(
        *(
            _shifted(sound.pieces(index, moment - shift, cancelled=cancelled), shift)
            for index, shift in sounds
        )
    )


def _shifted(found: Iterator[sound.Piece], shift: int) -> Iterator[sound.Piece]:
    for piece in found:
        yield dataclasses.replace(
            piece, ms=piece.ms + shift, end_ms=piece.end_ms + shift
        )


def has_sound(folder: Path) -> bool:
    """Whether a camera kept sound in any of its pieces (013): its recorder lists
    them as they close, so hours of pieces are never opened to find out."""
    return sound.heard_somewhere(folder)


@functools.cache
def _silent_piece(form: sound.Form) -> bytes | None:
    """A piece of AAC-LC silence of ``form``'s rate and channels, made once; None for
    another kind -- HE-AAC, another codec --, whose gaps stay jumps of time."""
    lc = form.codec == "aac" and bool(form.header) and form.header[0] >> 3 == 2
    if not lc:
        return None
    encoder = av.CodecContext.create("aac", "w")
    encoder.sample_rate, encoder.layout, encoder.format = form.rate, form.layout, "fltp"
    encoder.time_base = Fraction(1, form.rate)
    made: list[bytes] = []
    channels = av.AudioLayout(form.layout).nb_channels
    for n in range(4):  # past the encoder's priming: silence as such
        frame = av.AudioFrame.from_ndarray(
            np.zeros((channels, 1024), np.float32), format="fltp", layout=form.layout
        )
        frame.sample_rate, frame.pts = form.rate, n * 1024
        made.extend(bytes(packet) for packet in encoder.encode(frame))
    return made[-1] if made else None


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
        cancelled: Callable[[], bool] = lambda: False,
    ):
        self.path, self.first, self.form = path, first, form
        self.cancelled = cancelled  # asked as a long gap fills with silence
        self.partial = path.with_name(path.name + ".part")
        self.container = av.open(str(self.partial), "w", format="mp4")
        self.found = iter(()) if found is None else found
        self.piece: sound.Piece | None = None
        self.audio: Any = None
        self.heard_form: sound.Form | None = None
        self.heard_next: int | None = None  # where the sound written so far ends
        try:
            self.piece = next(self.found, None)
            while self.piece is not None and self.piece.ms < first:
                self.piece = next(self.found, None)  # before the file: no matter
            when = datetime.datetime.fromtimestamp(first / 1000, datetime.UTC)
            self.container.metadata["creation_time"] = when.isoformat()
            self.stream = self.container.add_stream_from_template(template)
            self.stream.time_base = MS
            if form[0] == "hevc":
                self.stream.codec_tag = "hvc1"  # QuickTime opens H.265 tagged so
            if self.piece is not None:
                try:
                    self.audio = self._sound_stream(self.piece)
                    self.heard_form = self.piece.form  # the one form its track holds
                except av.FFmpegError:
                    self.audio = None  # a sound MP4 will not take: the file without it
        except BaseException:  # a codec MP4 will not hold: no file left half made
            self.abandon()
            raise
        self.last_dts: int | None = None
        self.newest = first - 1  # the newest moment written

    def _sound_stream(self, piece: sound.Piece) -> Any:
        """The file's sound, made from the segment the first piece came from."""
        with retried(lambda: av.open(str(piece.path))) as heard:  # held a moment
            made = self.container.add_stream_from_template(heard.streams.audio[0])
        made.time_base = Fraction(1, piece.form.rate)
        return made

    def hear(self, up_to: int) -> None:
        """The pieces of sound at or before ``up_to`` written, each where it was heard
        -- on from the piece before when it is within half a piece of it, so the sound
        runs on --; those before the file's first frame left out."""
        while self.audio is not None and self.piece is not None:
            piece = self.piece
            at = piece.ms  # on the frames' moments
            if at > up_to:
                return
            self.piece = next(self.found, None)
            if at < self.first or piece.form != self.heard_form:
                continue  # before the file, or another form than its track holds
            rate = piece.form.rate
            length = round((piece.end_ms - piece.ms) * rate / 1000)
            frame_size = int(self.audio.codec_context.frame_size or length)
            pts = round((at - self.first) * rate / 1000)
            if (
                self.heard_next is not None
                and abs(pts - self.heard_next) <= frame_size // 2
            ):
                pts = self.heard_next
            if self.heard_next is not None and pts < self.heard_next:
                continue  # the time goes on, never back
            if self.heard_next is not None and pts > self.heard_next:
                pts = self._silence(piece.form, self.heard_next, pts, frame_size)
            self._put(piece.packet, pts, frame_size, rate)

    def _silence(self, form: sound.Form, at: int, until: int, size: int) -> int:
        """A gap from ``at`` to ``until`` filled with silent pieces: a player plays a
        file's sound piece after piece, and a jump of time would put what comes after
        it early by the gap's length. Where the next piece goes, on from them --
        ``until`` for a form no silent piece is made for."""
        silent = _silent_piece(form)
        if silent is None:
            return until
        count = round((until - at) / size)
        for n in range(count):
            if n % SILENCE_ASKS == 0 and self.cancelled():  # hours between sessions
                raise CancelledError
            if self.audio is None:
                break  # a silent piece refused: the sound ends there, the file goes on
            self._put(av.Packet(silent), at + n * size, size, form.rate)
        return at + count * size

    def _put(self, packet: av.Packet, pts: int, size: int, rate: int) -> None:
        if self.audio is None:
            return  # a piece refused before: the sound ended there
        packet.pts = packet.dts = pts
        packet.duration = size
        packet.time_base = Fraction(1, rate)
        packet.stream = self.audio
        try:
            self.container.mux(packet)
        except av.FFmpegError:
            self.audio = None  # a piece the muxer refuses: the sound ends there
            return
        self.heard_next = pts + size

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
