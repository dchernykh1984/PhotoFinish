"""A camera's recording: short Matroska segments, each with a sidecar of frame times.

The segment being written is ``current.mkv`` with ``current.times``, one
``<pts> <Unix ms>`` line a frame, both on disk as they are written. Once both are
closed they are renamed ``<YYYYmmdd-HHMMSS>-<n>``, the times first, so a closed
segment always has its times, and its name is appended to ``segments.txt``: readers
follow that list instead of the folder, which grows by thousands of files an hour. A
segment ends at the first frame a second after its start. Frames are encoded by an
encoder of the segment's own, so it starts with a keyframe (mpeg4, a keyframe every
15 frames, fixed quality 3); a network camera's packets are stored as they came, a
segment starting and ending at the camera's keyframes, its sound beside them
(specs/013), its timestamps from LEAD_MS on. A stretch without frames longer than
three frame intervals is appended to ``gaps.txt`` as ``<from ms> <to ms> <reason>``.
"""

from __future__ import annotations

import collections
import contextlib
import errno
import re
import time
from collections.abc import Callable, Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any, TextIO

import av
import numpy as np

from app.files import append, retried, write_in_one_step

SEGMENT_MS = 1000  # a segment's first frame is shown once it closes: SC-006's 2 s
# A phone sends again up to 7 s it may have lost (specs/007): the moments listed this
# far back are looked up, the last run's too, so the same frame is listed once.
RESENT_MS = 10_000
# A network camera's segment's timestamps start this far after its base: a piece of
# sound captured just before the keyframe that opens a segment comes after it, and a
# Matroska muxer handed a negative timestamp shifts every stream -- the frame times
# listed would no longer name the frames (specs/013).
LEAD_MS = 1000
CLOSED = "[0-9]*-[0-9]*-[0-9]*"  # a closed segment's name, without its suffix
NAMED = re.compile(r"\d{8}-\d{6}-\d{4,}")  # the same, exactly
SEGMENTS = "segments.txt"  # the closed segments' names, in the order they closed
SOUND = "sound.txt"  # those of them that kept sound (013): found without opening any
# The newest closed looked at for sound as a recorder starts: half a minute of them,
# as far back as the sound's reader looks for lines a scanner held (sound.UNHEARD).
LAST_LOOKED = 30
KEYFRAME_SLACK_MS = 100  # a camera's keyframe this much short of a second still cuts
CLOSING = "closing.name"  # the name a close gives, written before its two renames
READING = "reading.crash"  # there while a crash is read: one that kills is read once
ASIDE = "crashed.name"  # the stamp a crash kept aside takes, written before it does
_MS = Fraction(1, 1000)
MS_SCALE = Fraction(1, 1000)  # a millisecond in seconds
_GOP = 15
_QUALITY = 3
_QP2LAMBDA = 118  # FFmpeg's scale: quality 3 is global_quality 3 * 118
# Written as they come: a cluster a tenth of a second, and no stream waited for longer
# than that to interleave another's with -- a sound gone silent would hold the frames
# back for ten seconds, FFmpeg's default, and a crash would lose them (specs/013).
_AS_IT_COMES = {
    "flush_packets": "1",
    "cluster_time_limit": "100",
    "max_interleave_delta": "100000",
}


class SegmentWriter:
    """Writes one camera's frames into ``folder``; ``close`` ends the open segment."""

    def __init__(
        self,
        folder: Path,
        fps: float,
        segment_ms: int = SEGMENT_MS,
        closed: list[str] | None = None,  # what ``recover`` gave, when it was just run
        sound: bool = True,  # its camera's sound read: a track kept for it (013)
    ) -> None:
        self.folder, self.fps, self.segment_ms = folder, fps, segment_ms
        self.sound = sound
        closed = recover(folder) if closed is None else closed
        self.segments = len(closed)
        self.frames = 0
        self._last_ms: int | None = None  # this run's newest frame: frames keep order
        # The moments the run before listed in its last RESENT_MS, oldest first, and
        # as a set to look a frame sent again up in. Its newest frame: a gap from it
        # noted once, never a frame dropped for it -- a clock set back between runs
        # still records.
        self._recent = collections.deque(_recent_recorded(folder, closed, RESENT_MS))
        self._listed = set(self._recent)
        self._before_ms = self._recent[-1] if self._recent else None
        self.gap_reason = "restart" if self._before_ms is not None else "no frames"
        self._open: _Encoded | _Remuxed | None = None
        self._heard_ms: int | None = None  # the newest piece of sound kept (013)
        # A connection's first pieces may be ones sent again, until its first new one.
        self._heard_again = True
        # A connection's first frames may be ones sent again: a restart's, or after
        # the camera hung up (``hung_up``), until the first new one.
        self._resending = True
        self._unlisted: list[str] = []  # closed, the list refused their names so far
        self._unheard: list[str] = []  # kept sound, the sound list refused them so far

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
        at a keyframe; packets before the first are of no use and are dropped. A
        connection's first ones whose moments were listed lately -- the frames a
        phone sends again after a break, with the moments they were sent with
        (specs/007) -- are written for the frames after them to decode, and not
        listed: the recording lists each frame once. From its first new frame on, a
        moment set back on a listed one is another frame's, and listed."""
        if packet.pts is None or packet.dts is None or packet.stream is None:
            return  # nothing to place it by
        if not isinstance(self._open, _Remuxed) and not packet.is_keyframe:
            return
        stream = packet.stream
        again = self._resending and ms in self._listed
        self._resending = again
        # A camera's keyframes a second apart cut each one, a moment early or late.
        cut = packet.is_keyframe
        self._next(ms, cut=cut, slack=KEYFRAME_SLACK_MS, listed=not again)
        opened = self._segment(
            _Remuxed, lambda: _Remuxed(self.folder, packet, stream, ms, self.sound)
        )
        opened.add(packet, packet.pts, packet.dts, None if again else ms)
        if not again:
            self.frames += 1
            self._recent.append(ms)
            self._listed.add(ms)
            while self._recent and self._recent[0] < ms - RESENT_MS:
                self._listed.discard(self._recent.popleft())

    def write_audio(self, packet: av.Packet, ms: int) -> bool:
        """A piece of a network camera's sound, placed at ``ms`` by the frame before
        it (specs/013): into the open segment beside its frames. A connection's first
        pieces not after the newest kept by half their length -- sent again after a
        loss -- are not, until its first new one: after it each piece comes once,
        though placed a little back by a frame placed late. Nor one before any
        segment, which has no frame to be placed by. Whether it was kept."""
        if packet.pts is None or packet.dts is None or packet.stream is None:
            return False
        half = in_ms(packet.duration or 0, fraction(packet.time_base)) // 2
        heard = self._heard_ms
        if self._heard_again and heard is not None and ms < heard + max(half, 1):
            return False
        if isinstance(self._open, _Remuxed) and self._open.add_audio(packet):
            self._heard_again = False
            self._heard_ms = ms if heard is None else max(heard, ms)
            return True
        return False

    @property
    def newest_ms(self) -> int | None:
        """This run's newest frame listed: how far behind live a phone is (007)."""
        return self._last_ms

    def hung_up(self) -> None:
        """The camera hung up, its segment closed: the gap before its next frame is
        a reconnect's, and its next connection may begin with frames sent again."""
        self.gap_reason = "reconnect"
        self._resending = True
        self._heard_again = True

    def _segment[T: (_Encoded, _Remuxed)](
        self, kind: type[T], begun: Callable[[], T]
    ) -> T:
        """The open segment when it is of ``kind``; else the open one closed, one that
        failed to close finished or its whole frames made a segment, the rest kept
        aside, and a new one begun."""
        opened = self._open if isinstance(self._open, kind) else None
        if opened is None:
            self.close()
            for name in _see_to(self.folder, self.segments + 1):  # a failed close
                self._closed(name)
            opened = begun()
            self._open = opened
        return opened

    def _next(self, ms: int, cut: bool, slack: int = 0, listed: bool = True) -> None:
        """A gap before ``ms`` noted; the open segment closed when it is long enough
        and ``ms`` may start the next. A frame not listed -- sent again -- notes no
        gap, nor moves the newest frame: the gaps it falls in are noted already."""
        if listed:
            last = self._last_ms if self._last_ms is not None else self._before_ms
            self._before_ms = None
            if last is not None and ms - last > 3 * 1000 / self.fps:
                self._gap(last, ms)
            elif last is not None:  # a reconnect or restart frames sent again filled
                self.gap_reason = "no frames"
        if (
            cut
            and self._open is not None
            and ms - self._open.first_ms >= self.segment_ms - slack
        ):
            self.close()
        if listed:
            self._last_ms = max(ms, self._last_ms or ms)

    def close(self) -> None:
        """End the open segment: both files closed, then renamed, the times first."""
        if self._open is None:
            return
        segment, self._open = self._open, None
        segment.close()
        name = _name(self.folder, segment.first_ms, self.segments + 1)
        meant = self.folder / CLOSING  # a kill or a refused rename between the two
        meant.write_text(name, encoding="ascii")  # is finished by it, exactly
        (self.folder / "current.times").replace(self.folder / f"{name}.times")
        (self.folder / "current.mkv").replace(self.folder / f"{name}.mkv")
        _forget(meant)
        if isinstance(segment, _Remuxed) and segment.heard:
            self._unheard.append(name)
        self._heard_listed()
        self._closed(name)

    def _heard_listed(self) -> None:
        """The segments that kept sound listed, with any the list refused before:
        before their own lines, so a kill between the two leaves them to the recovery,
        which lists their sound again. A sound list refused costs no close."""
        if not self._unheard:
            return
        heard = "".join(f"{closed}\n" for closed in self._unheard)
        with contextlib.suppress(OSError):  # the next close takes them
            append(self.folder / SOUND, heard.encode("ascii"))
            self._unheard = []

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
        try:
            for packet in self.stream.encode(None):
                self.container.mux(packet)
            self.container.close()
        finally:  # a video that will not close holds no times open (Windows)
            self.times.close()


class _Remuxed:
    """A camera's packets stored as they came, from its first keyframe on, its sound
    beside them on the same timestamps (specs/013)."""

    def __init__(
        self,
        folder: Path,
        first: av.Packet,
        template: av.stream.Stream,
        ms: int,
        sound: bool = True,
    ) -> None:
        self.first_ms = ms
        rate = first.time_base
        self.time_base = Fraction(rate.numerator, rate.denominator)
        # Timestamps from LEAD_MS on in each segment: none of its sound below 0.
        self.base = (first.dts or 0) - round(LEAD_MS * MS_SCALE / self.time_base)
        self.container = _video(folder)
        self.stream = self.container.add_stream_from_template(template)
        # Its sound kept when it is read and AAC (specs/013): what the phones and
        # streaming apps send, played and exported; an IP camera's G.711, which
        # Matroska will not hold, costs the sound alone, never the video. No track
        # for a sound never read: an empty one would be taken for sound.
        heard = [
            s
            for s in template.container.streams.audio
            if sound and s.codec_context.name == "aac"
        ]
        self.audio = (
            self.container.add_stream_from_template(heard[0]) if heard else None
        )
        if self.audio is not None:
            try:
                self.container.start_encoding()  # the header now, with its sound
            except av.FFmpegError:
                # A config the muxer cannot read: the segment begun again without it.
                with contextlib.suppress(av.FFmpegError, OSError):
                    self.container.close()
                self.container = _video(folder)
                self.stream = self.container.add_stream_from_template(template)
                self.audio = None
        self.audio_dts: int | None = None  # the newest piece's: the muxer wants order
        self.heard = False  # a piece of sound kept in it
        self.times: TextIO = _times(folder)

    def add_audio(self, packet: av.Packet) -> bool:
        """A piece of the camera's sound stored on the video's timestamps; False when
        the segment has no sound, or it came more than LEAD_MS before its base."""
        if self.audio is None or packet.pts is None or packet.dts is None:
            return False
        base = round(self.base * self.time_base / fraction(packet.time_base))
        pts, dts = packet.pts - base, packet.dts - base
        if pts < 0 or dts < 0:
            return False
        if self.audio_dts is not None and dts <= self.audio_dts:
            return False  # out of order: a muxer refuses it, and the recorder with it
        self.audio_dts = dts
        packet.pts, packet.dts = pts, dts
        packet.stream = self.audio
        try:
            self.container.mux(packet)
        except av.FFmpegError:
            self.audio = None  # a sound the muxer refuses costs the sound alone
            return False
        self.heard = True
        return True

    def add(self, packet: av.Packet, pts: int, dts: int, ms: int | None) -> None:
        """The packet stored; its time listed unless ``ms`` is None."""
        packet.pts, packet.dts = pts - self.base, dts - self.base
        pts_ms = in_ms(pts - self.base, self.time_base)
        packet.stream = self.stream
        self.container.mux(packet)
        if ms is not None:
            self.times.write(f"{pts_ms} {ms}\n")

    def close(self) -> None:
        try:
            self.container.close()
        finally:  # a video that will not close holds no times open (Windows)
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


def fraction(rate: Any) -> Fraction:
    """A stream's or a packet's time base as a Fraction; a millisecond without one."""
    return _MS if rate is None else Fraction(rate.numerator, rate.denominator)


def in_ms(value: int, time_base: Fraction) -> int:
    """``value`` in ``time_base`` as whole milliseconds, rounded as the muxer rounds:
    to the nearest, a half away from zero (FFmpeg's AV_ROUND_NEAR_INF), a negative
    pts of an open GOP's leading frame too."""
    scaled = abs(value * time_base * 1000)
    near = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    return near if value >= 0 else -near


def _size(image: np.ndarray | av.VideoFrame) -> tuple[int, int]:
    if isinstance(image, av.VideoFrame):
        return image.height, image.width
    return image.shape[0], image.shape[1]


def _list_missing(folder: Path) -> list[str]:
    """Every closed segment's name, the list completed with any a crash closed but
    did not list; once, when a recorder starts."""
    try:
        # read as its readers read it: a byte not ASCII names no segment, stops nothing,
        # and a name a kill cut short counts for none
        text = (folder / SEGMENTS).read_bytes().decode("utf-8", "replace")
        listed = [name for name in text.split() if NAMED.fullmatch(name)]
    except OSError:
        listed = []
    known = set(listed)
    with contextlib.suppress(OSError):  # held a moment: listed as it is named
        if held := _meant(folder):
            known.add(held[0])  # its recovery lists it as it forgets the name
    missing = sorted(
        path.stem
        for path in folder.glob(f"{CLOSED}.mkv")
        if path.stem not in known and path.with_suffix(".times").exists()
    )
    if missing:
        _list_sound(folder, missing)  # first, as a close lists it: read by its list
        append(folder / SEGMENTS, "".join(f"{n}\n" for n in missing).encode("ascii"))
    return listed + missing


def _list_unheard(folder: Path, names: list[str]) -> None:
    """The newest closed segments that kept sound and are not listed as such -- the
    line of a recorder's last close refused, kept for a close that never came --
    listed now."""
    try:
        heard = set((folder / SOUND).read_bytes().decode("ascii", "replace").split())
    except FileNotFoundError:
        heard = set()
    except OSError:
        return  # held a moment: the next start looks again
    _list_sound(folder, [name for name in names if name not in heard])


def _list_sound(folder: Path, names: list[str]) -> None:
    """Those of ``names`` -- closed by a recovery, not by their own close -- whose
    video kept sound, listed as a close lists them. A list refused costs their sound
    alone, never the recovery; a full disk is said."""
    heard = "".join(f"{n}\n" for n in names if _keeps_audio(folder / f"{n}.mkv"))
    if not heard:
        return
    try:
        append(folder / SOUND, heard.encode("ascii"))
    except OSError as error:
        if error.errno == errno.ENOSPC:
            raise


def _keeps_audio(path: Path) -> bool:
    try:
        return kept_sound(path)
    except av.FFmpegError, OSError:
        return False


def kept_sound(path: Path) -> bool:
    """Whether a closed segment holds a piece of sound -- a track alone, of a stream
    that said AAC and sent none, is no sound --; raises as ``av.open`` does."""
    with retried(lambda: av.open(str(path))) as container:  # a copy held a moment
        heard = container.streams.audio
        return bool(heard) and any(p.size for p in container.demux(heard[0]))


def recover(folder: Path) -> list[str]:
    """Every closed segment's name once what a crash left is seen to: a closed one
    it did not list listed, the frames it left whole in ``current.*`` made one, the
    rest kept aside. A recorder does it as it starts, before its camera is back."""
    folder.mkdir(parents=True, exist_ok=True)
    _finish_recovery(folder)  # one a kill cut short; listed with the others just below
    closed = _list_missing(folder)
    _list_unheard(folder, closed[-LAST_LOOKED:])
    if names := _see_to(folder, len(closed) + 1):
        listed = "".join(f"{name}\n" for name in names)
        append(folder / SEGMENTS, listed.encode("ascii"))  # else at the next start
        closed.extend(names)
    return closed


def _see_to(folder: Path, n: int) -> list[str]:
    """What a crash or a failed close left: a recovery not yet named named first,
    then a close cut between its renames finished, else the whole frames of
    ``current.*`` made a closed segment numbered ``n`` or after, the rest kept
    aside. The names of the segments it closed, in order, for the caller to list;
    those that kept sound listed as such already."""
    pending = (folder / RECOVERED_NAME).exists()  # its copy refused its name
    finished = _finish_recovery(folder) if pending else None
    if not (folder / "current.mkv").exists():
        closed = [finished] if finished else []  # the usual case: two looks, no more
    else:
        name = _finish_close(folder) or _recover(folder, n)
        _keep_aside(folder)
        closed = [c for c in (finished, name) if c]
    _list_sound(folder, closed)
    return closed


def _finish_close(folder: Path) -> str | None:
    """A close a kill or a refused rename cut between its two renames: the times
    have the name it wrote first, the video is still ``current.mkv`` and takes that
    name too. Nothing is guessed: no written name, or one that does not fit, and the
    video is left to be recovered. The name, or None. A rename refused again is
    raised: that video waits for its own name, never kept aside without its times
    nor written over by the next segment."""
    meant = folder / CLOSING
    try:
        name = meant.read_text(encoding="ascii").strip()
    except OSError, ValueError:
        return None
    cut = (
        NAMED.fullmatch(name)
        and not (folder / "current.times").exists()
        and (folder / f"{name}.times").exists()
        and not (folder / f"{name}.mkv").exists()
    )
    if cut:
        (folder / "current.mkv").replace(folder / f"{name}.mkv")
    _forget(meant)  # done, or a name that fits nothing here
    return name if cut else None


def _forget(meant: Path) -> None:
    """A name written before two renames, both done: one a scanner holds stays, and
    fits nothing next time, as both files have their names by then."""
    with contextlib.suppress(OSError):
        meant.unlink(missing_ok=True)


def _name(folder: Path, first_ms: int, n: int) -> str:
    """A closed segment's name: its first frame's time, a number no other has --
    neither a video nor times left alone, whose video went aside, nor a recovery
    whose copy is still to take it."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(first_ms / 1000))
    held = None
    with contextlib.suppress(OSError):  # held a moment: named in a second as it is
        held = _meant(folder)
    taken = held[0] if held else ""
    while f"{stamp}-{n:04d}" == taken or any(
        (folder / f"{stamp}-{n:04d}{suffix}").exists() for suffix in (".mkv", ".times")
    ):
        n += 1
    return f"{stamp}-{n:04d}"


RECOVERED_MKV = "recovered.mkv"  # a recovery under way: its copy,
RECOVERED_TIMES = "recovered.times"  # the copy's times,
RECOVERED_NAME = "recovered.name"  # and the name it is to take, written last


def _recover(folder: Path, n: int) -> str | None:
    """The frames a crash left whole in ``current.*``, with their times, made a
    closed segment for the caller to list: its name, or None when it holds none.
    The copy and its times are written, then the name it is to take, and only then
    is the crash kept aside and the copy named: a kill before the name is written
    leaves the crash to recover again, one after it is finished as meant by the next
    start. Neither shows a frame twice, nor loses one, nor guesses. A crash that
    brought the recorder down as it was read, libav and all, is kept aside unread
    at the next start, not read again by every recorder that starts."""
    copy, copied = folder / RECOVERED_MKV, folder / RECOVERED_TIMES
    meant = folder / RECOVERED_NAME
    if meant.exists():  # one not named yet is never written over:
        return None  # this crash goes aside whole
    reading = folder / READING
    if reading.exists():
        return None  # the last read of it never ended: it goes aside unread
    try:
        frames = frame_times(folder / "current.times")
        reading.touch()
        kept = _copy_whole(folder / "current.mkv", copy, frames)
        with contextlib.suppress(OSError):  # read to its end; one held a moment is
            reading.unlink()  # cleared as the crash goes aside
        if not kept:
            copy.unlink(missing_ok=True)
            return None
        name = _name(folder, kept[0][1], n)
        times = "".join(f"{pts} {ms}\n" for pts, ms in kept)
        write_in_one_step(copied, times.encode("ascii"))
        # its source's first line too, as _first_ms reads it: a later crash is not
        # taken for it, nor it for a later one
        source = next(iter(frames.values()))
        write_in_one_step(meant, f"{name} {source}".encode("ascii"))
    except (OSError, ValueError, IndexError, av.FFmpegError) as error:
        with contextlib.suppress(OSError):  # read to an error it said: no crash
            reading.unlink(missing_ok=True)  # that kills, nor one left unread
        _drop_recovery(folder)  # what the crash left is where it was
        if isinstance(error, OSError) and error.errno == errno.ENOSPC:
            raise  # the disk full, said so: the crash recovered once there is room
        return None
    try:
        _keep_aside(folder)
        _name_recovery(folder, name)
    except OSError:
        return None  # finished as meant at the next start
    return name


def _finish_recovery(folder: Path) -> str | None:
    """A recovery a kill cut short, or one whose copy could not be named: once the
    name it was to take is written, done as meant -- what it recovered kept aside,
    its copy named; before, dropped, the crash left to recover again. ``current.*``
    goes aside only when it is that recovery's source, by its first frame's time: a
    later crash's is recovered in its turn. The name given, for the caller to list."""
    try:
        meant = _meant(folder)
    except OSError:
        return None  # held a moment: tried again as the next segment starts
    if meant is None:
        _drop_recovery(folder)
        return None
    name, first_ms = meant
    try:
        if _first_ms(folder / "current.times") == first_ms:
            _keep_aside(folder)
        _name_recovery(folder, name)
    except OSError:
        return None  # tried again later
    return name


def _meant(folder: Path) -> tuple[str, int] | None:
    """The name a recovery's copy is to take and its source's first time, once
    written whole; None before. One there but held a moment raises: not taken for
    none, so its copy is not dropped."""
    try:
        meant = (folder / RECOVERED_NAME).read_text(encoding="ascii").split()
        name, first_ms = meant[0], int(meant[1])
    except FileNotFoundError, ValueError, IndexError:
        return None
    return (name, first_ms) if NAMED.fullmatch(name) else None


def _first_ms(times: Path) -> int | None:
    """The time of the first frame a times file has, or None."""
    try:
        return next(iter(frame_times(times).values()), None)
    except OSError, ValueError:
        return None


def _name_recovery(folder: Path, name: str) -> None:
    """A recovery's copy given its name, the times first, then the name it was to
    take forgotten."""
    for left, suffix in ((RECOVERED_TIMES, ".times"), (RECOVERED_MKV, ".mkv")):
        if (folder / left).exists():
            (folder / left).replace(folder / f"{name}{suffix}")
    (folder / RECOVERED_NAME).unlink(missing_ok=True)


def _drop_recovery(folder: Path) -> None:
    """What a recovery copied before it wrote the name it was to take."""
    for left in (RECOVERED_MKV, RECOVERED_TIMES, RECOVERED_NAME):
        with contextlib.suppress(OSError):
            (folder / left).unlink(missing_ok=True)


def frame_times(times: Path) -> dict[int, int]:
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
    into a file of their own, which ends as a file should, its sound with them
    (specs/013); the frames' ``(pts, ms)``."""
    kept: set[int] = set()
    with av.open(str(left)) as video, av.open(str(copy), "w", format="matroska") as out:
        into = out.add_stream_from_template(video.streams.video[0])
        heard = video.streams.audio
        sound = out.add_stream_from_template(heard[0]) if heard else None
        for packet, pts in _whole(video):
            if packet.stream.type == "audio":
                if sound is None:
                    continue
                packet.stream = sound
                try:
                    out.mux(packet)
                except av.FFmpegError:
                    sound = None  # a sound the copy refuses costs the sound alone
            elif pts in frames:
                packet.stream = into
                out.mux(packet)
                kept.add(pts)
    return [(pts, ms) for pts, ms in frames.items() if pts in kept]


def _whole(video: av.container.InputContainer) -> Iterator[tuple[av.Packet, int]]:
    """The video's packets, and its sound's, that came whole, each with its pts in
    ms, up to where a crash cut the file, read as any error."""
    streams = [video.streams.video[0], *video.streams.audio[:1]]
    try:
        for packet in video.demux(*streams):
            if packet.size and packet.pts is not None:
                yield packet, in_ms(packet.pts, fraction(packet.time_base))
    except av.FFmpegError:
        return  # the cluster the crash cut short: what came before is kept


def _keep_aside(folder: Path) -> None:
    """A segment a crash, or a failed close, left open is not one to show, but what
    it holds is kept: both files under one stamp, the times first. The stamp is
    written before the two renames, so one a kill or a refused rename cut between
    them is finished by it: the video joins its own times, no others."""
    times, video = folder / "current.times", folder / "current.mkv"
    if not (times.exists() or video.exists()):
        return  # kept aside already, or named: nothing left open
    meant = folder / ASIDE
    try:
        stamp = meant.read_text(encoding="ascii").strip()
    except OSError, ValueError:
        stamp = ""
    cut = (
        stamp.isdigit()
        and not times.exists()
        and (folder / f"crashed-{stamp}.times").exists()
        and not (folder / f"crashed-{stamp}.mkv").exists()
    )
    if not cut:
        ms = time.time_ns() // 1_000_000
        while any((folder / f"crashed-{ms}{s}").exists() for s in (".mkv", ".times")):
            ms += 1  # never over a crash kept aside in the same millisecond
        stamp = str(ms)
        if times.exists() and video.exists():  # two renames: one cut between them
            meant.write_text(stamp, encoding="ascii")  # is finished by it
    for left in (times, video):
        if left.exists():
            left.replace(folder / f"crashed-{stamp}{left.suffix}")
    _forget(meant)
    (folder / READING).unlink(missing_ok=True)  # the crash it was there for is aside


def _recent_recorded(folder: Path, closed: list[str], span_ms: int) -> list[int]:
    """The moments of the run before's frames within ``span_ms`` of its newest, oldest
    first: the last segments' times, a few at a recorder's start."""
    found: list[int] = []
    for name in reversed(closed):
        try:
            text = (folder / f"{name}.times").read_text(encoding="ascii").split()
        except OSError, ValueError:  # cut short by a kill, or garbled: the one before
            continue
        moments = [int(ms) for ms in text[1::2] if ms.isdigit()]
        found = moments + found
        if found and moments and min(moments) < max(found) - span_ms:
            break
    newest = max(found, default=0)
    return sorted(ms for ms in found if ms >= newest - span_ms)
