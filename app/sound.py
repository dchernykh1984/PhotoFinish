"""A camera's sound from a moment, as it is played (specs/013-sound).

A segment keeps a network camera's sound beside its frames, on the frames' timestamps;
a piece of sound's moment is the frame nearest it in the segment's times, moved by
the distance between their timestamps. Consecutive segments overlap by up to LEAD_MS
-- a piece captured before the keyframe that opens a segment comes after it -- so the
pieces are put in order across them, and one that overlaps the piece before -- sent
again after a loss, kept by a recorder started again -- is dropped. They are decoded
on one decoder, so the sound runs on across a segment's end, a gap between pieces
made silence of its length, and played at a rate with FFmpeg's ``atempo``, which
keeps the pitch.
"""

from __future__ import annotations

import heapq
import threading
import time
import weakref
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import numpy as np

from app.files import Appended
from app.recorder import folder_of
from app.recorder.segments import LEAD_MS, SOUND, fraction, in_ms
from app.video_index import VideoIndex, read_times

# A piece this much after the end of the one before: silence between. Under a piece's
# 21 ms, so one the decoder gave nothing for -- its first, one damaged -- is silence of
# its length, and over the moments' rounding to the millisecond.
GAP_MS = 10
PREROLL_MS = 50  # decoded before the moment asked and dropped: no click as it begins
SILENCE_MS = 100  # a gap's silence made this much at a time
# Following a recording, its last segment's sound is given up to this long before its
# last frame: a piece and the frame beside it lie this far apart in a stream at most.
FOLLOW_SLACK_MS = 200
# The newest segments not listed as sounding, looked at again as more come: half a
# minute of them, a list held by a scanner that long.
UNHEARD = 30
HELD_READS, HELD_PAUSE_S = 3, 0.05  # a segment's times held a moment: read again
# atempo's range: faster in one stage, as each stage's window puts the sound earlier
# by its lag -- x4 some 40 ms on the recording's time, two stages of x2 some 70 --;
# slower chained, from x0.5 down.
ATEMPO_MOST = 100.0
ATEMPO_LEAST = 0.5
MS = Fraction(1, 1000)


@dataclass(frozen=True)
class Form:
    """What a piece is decoded with: its codec, header, rate and channels."""

    codec: str
    header: bytes
    rate: int
    layout: str


@dataclass(order=True)
class Piece:
    """A piece of sound at its moment, in the order played."""

    ms: int
    end_ms: int = field(compare=False)
    packet: av.Packet = field(compare=False)
    form: Form = field(compare=False)
    path: Path = field(compare=False)  # the segment it came from


def phone_mates(
    chosen: Mapping[str, Any], cameras: Iterable[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """The other cameras of ``chosen``'s phone, as the camera dialog notes a phone's
    lenses (``phone``): the ones whose sound it takes when its own has none."""
    phone = chosen.get("phone")
    return [c for c in cameras if c is not chosen and phone and c.get("phone") == phone]


def whose(
    chosen: Mapping[str, Any],
    cameras: Iterable[Mapping[str, Any]],
    heard: Callable[[Mapping[str, Any]], bool],
) -> Mapping[str, Any] | None:
    """Whose sound goes with ``chosen``: its own when ``heard`` says it has some, else
    the first of its phone's other cameras that has -- the lens that kept it; None."""
    for camera in (chosen, *phone_mates(chosen, cameras)):
        if heard(camera):
            return camera
    return None


def heard_at(index: VideoIndex, moment: int, within: int) -> bool:
    """Whether a camera's recording has sound at ``moment``, on its own times: in
    the segment of its frame within ``within`` ms of it, as its recorder lists those
    that kept sound -- the pieces played are those alone."""
    place = index.nearest(moment, within=within)
    return place is not None and index.frame(place).path.stem in sounding(index.folder)


_SOUNDING: dict[Path, tuple[Appended, frozenset[str], bytes | None]] = {}
_SOUNDING_LOCK = threading.Lock()  # the window's thread and an export's ask


def sounding(folder: Path) -> frozenset[str]:
    """The names of a camera's segments that kept sound, as its recorder lists them
    as they close (SOUND): followed as the list grows, a line a second all day, the
    lines added since the last ask read alone. A list begun anew -- its folder
    cleared -- begins with another line, or is shorter: read from its start. One
    held a moment, unreadable, gives what it listed so far."""
    with _SOUNDING_LOCK:
        follower, names, seen = _SOUNDING.get(folder, (None, frozenset(), None))
        try:
            file = _first_line(folder / SOUND)
        except OSError:
            return names  # held by a scanner a moment (Windows): not gone
        if follower is None or file != seen:
            follower, names = Appended(folder / SOUND), frozenset()
        before = follower.offset
        found = follower.new_lines()
        if follower.offset < before:
            names = frozenset()
        if found:  # made anew only as lines come, never at each ask
            names = names | frozenset(found)
        _SOUNDING[folder] = (follower, names, file)
        return names


def _first_line(path: Path) -> bytes | None:
    """A list's first line: another, the list begun anew, whatever its inode -- which
    a filesystem may give a file made again; None when there is none. Raises when it
    is there and cannot be read."""
    try:
        with path.open("rb") as f:
            return f.readline(64)
    except FileNotFoundError:
        return None


def heard_somewhere(folder: Path) -> bool:
    """Whether a camera kept sound in any of its segments: its recorder lists those
    that did as they close."""
    try:
        return (folder / SOUND).stat().st_size > 0
    except OSError:
        return False


def heard_later(index: VideoIndex, moment: int) -> bool:
    """Whether a camera kept sound in a segment from ``moment`` on, on its own times:
    one allowed the microphone later is heard in its turn, the pieces following as
    it plays -- never one whose sound is all behind it, a gap's before as much.
    Asked at each poll: told at once while no segment nor sound line came since."""
    kept = sounding(index.folder)
    if not kept:
        return False
    seen = _NEWEST.get(index)
    if seen is None or seen[0] is not kept or seen[1] != len(index.paths):
        seen = (kept, len(index.paths), index.newest_end_of(kept))
        _NEWEST[index] = seen
    return seen[2] is not None and seen[2] >= moment


# The newest end of each index's segments that kept sound, as the list and the index
# were when it was found: found again only as they grow.
_NEWEST: weakref.WeakKeyDictionary[
    VideoIndex, tuple[frozenset[str], int, int | None]
] = weakref.WeakKeyDictionary()


def playing_from(
    chosen: Mapping[str, Any],
    cameras: Iterable[Mapping[str, Any]],
    index_of: Callable[[Mapping[str, Any]], VideoIndex],
    moment: int,
    within: int,
) -> Mapping[str, Any] | None:
    """Whose sound plays from ``moment`` on the video's time with ``chosen``: a
    camera of its phone's with sound there -- its own first --, else one with sound
    later; None."""
    listed = list(cameras)

    def there(camera: Mapping[str, Any]) -> bool:
        own = moment - int(camera.get("offset_ms", 0))
        return heard_at(index_of(camera), own, within)

    def later(camera: Mapping[str, Any]) -> bool:
        return heard_later(index_of(camera), moment - int(camera.get("offset_ms", 0)))

    return whose(chosen, listed, there) or whose(chosen, listed, later)


def shift_ms(own: Mapping[str, Any], heard: Mapping[str, Any]) -> int:
    """How much later than its own moments ``heard``'s sound goes in ``own``'s video:
    the two cameras' offsets apart, as it plays."""
    return int(heard.get("offset_ms", 0)) - int(own.get("offset_ms", 0))


def exported_sound(
    own: Mapping[str, Any], cameras: Iterable[Mapping[str, Any]]
) -> list[tuple[Path, int]]:
    """Whose sound ``own``'s exported file takes: its own and its phone's other
    lenses' that kept some -- the phone's sound, whichever lens kept it at each
    moment, as it plays --, each with how much later it goes: the two offsets apart.
    None kept any: none."""
    phone = [own, *phone_mates(own, cameras)]
    return [
        (folder_of(str(camera["id"])), shift_ms(own, camera))
        for camera in phone
        if heard_somewhere(folder_of(str(camera["id"])))
    ]


def pieces(
    index: VideoIndex,
    from_ms: int,
    follows: bool = False,
    cancelled: Callable[[], bool] = lambda: False,
) -> Pieces:
    """The camera's pieces of sound from ``from_ms`` on its own times, in order, each
    once -- and the one before it, PREROLL_MS, for a decoder to begin on --: from the
    segment before the one of the frame at ``from_ms``, whose sound may reach past
    its end. The segments are listed now, on the caller's thread, which refreshes
    the index; their files are read as the pieces are asked for. ``follows``: the
    recording grows as it plays, the segments closed since added (Pieces.extend).
    ``cancelled`` asked between segments ends them, as ``Pieces.cancel`` does."""
    place = index.at_or_before(from_ms)
    found = [] if place is None else index.segments_from(place)
    return Pieces(found, from_ms, follows, cancelled, index.folder)


class Pieces:
    """A camera's pieces of sound, in order, each once (an iterator) -- of the
    segments listed as it was made, and, following a recording that grows, of those
    ``extend`` adds: at the last listed it gives the pieces no next segment's can come
    before, and waits for more until ``finish``."""

    def __init__(
        self,
        found: list[Path],
        from_ms: int,
        follows: bool,
        cancelled: Callable[[], bool] = lambda: False,
        folder: Path | None = None,
    ) -> None:
        # Those that kept sound alone, as its recorder lists them (``folder``'s):
        # hours of segments without are never opened for it.
        self._folder = folder
        self._unheard: list[Path] = []  # the newest not listed as sounding yet
        self._found = self._sounding(found)
        self._known = set(self._found)  # those in _found, looked up as more come
        self._from_ms = from_ms
        self._more = threading.Condition()
        self._finished = not follows
        self._asked = cancelled
        self._cancelled = False
        self._made = self._in_order()

    def __iter__(self) -> Pieces:
        return self

    def __next__(self) -> Piece:
        return next(self._made)

    def extend(self, paths: Iterable[Path]) -> None:
        """Segments closed since, in the order they closed: on the caller's thread.
        The newest not listed as sounding -- a line its close could not write, written
        with the next -- are looked at again with them."""
        found = self._sounding([*self._unheard, *paths])
        with self._more:
            new = [path for path in dict.fromkeys(found) if path not in self._known]
            self._found.extend(new)
            self._known.update(new)
            self._more.notify_all()

    def _sounding(self, paths: Iterable[Path]) -> list[Path]:
        listed = list(paths)
        if self._folder is None:
            return listed
        kept = sounding(self._folder)
        self._unheard = [path for path in listed if path.stem not in kept][-UNHEARD:]
        return [path for path in listed if path.stem in kept]

    def finish(self) -> None:
        """No more to wait for: what is held given, then the end."""
        with self._more:
            self._finished = True
            self._more.notify_all()

    def cancel(self) -> None:
        """Ended where they are: no segment read after the one being read."""
        with self._more:
            self._cancelled = self._finished = True
            self._more.notify_all()

    def _ended(self) -> bool:
        return self._cancelled or self._asked()

    def _segment(self, k: int, waits: bool) -> Path | None:
        """The ``k``-th segment; ``waits``, until it comes or there are no more."""
        with self._more:
            while waits and k >= len(self._found) and not self._finished:
                self._more.wait(0.2)
            return self._found[k] if k < len(self._found) else None

    def _in_order(self) -> Iterator[Piece]:
        held: list[Piece] = []
        self._last_end: int | None = None
        k, path = 0, self._segment(0, waits=True)
        while path is not None:
            if self._ended():
                return  # stopped, cancelled: no segment read on for nobody
            held.extend(_pieces_of(path))
            heapq.heapify(held)
            yield from self._given(held, self._safe(path, k))
            k, path = k + 1, self._segment(k + 1, waits=True)
        if not self._ended():
            yield from self._given(held, None)  # finished: the rest, in order

    def _safe(self, path: Path, k: int) -> int | None:
        """Before when the pieces held may go, segment ``k`` at ``path`` read: none
        of the next segment's can come before it. None: all of them."""
        after = self._segment(k + 1, waits=False)
        if after is not None:
            # A piece of the next segment comes LEAD_MS before its first frame at most.
            return _first_ms(after) - LEAD_MS
        if not self._finished:
            # Waiting for the next: what comes before the last frame by more than
            # sound and frames lie apart in a stream.
            return _last_ms(path) - FOLLOW_SLACK_MS
        return None

    def _given(self, held: list[Piece], safe: int | None) -> Iterator[Piece]:
        """The pieces held before ``safe`` -- all, None --, in order, each once."""
        while held and (safe is None or held[0].ms < safe) and not self._ended():
            piece = heapq.heappop(held)
            if piece.end_ms <= self._from_ms - PREROLL_MS:
                continue  # before the moment asked
            last = self._last_end
            if last is not None and piece.ms < last - _half(piece):
                continue  # heard already: sent again, or kept by a run before
            self._last_end = piece.end_ms
            yield piece


def _half(piece: Piece) -> int:
    return (piece.end_ms - piece.ms) // 2


def _times_of(path: Path) -> np.ndarray | None:
    """A segment's times, read again a moment on when they cannot be read -- held by
    a scanner (Windows) --: a listed segment's sound never taken for none at once."""
    for _ in range(HELD_READS):
        if (times := read_times(path)) is not None:
            return times
        time.sleep(HELD_PAUSE_S)
    return read_times(path)


def _first_ms(path: Path) -> int:
    times = _times_of(path)
    return int(times[0, 1]) if times is not None and len(times) else 0


def _last_ms(path: Path) -> int:
    times = _times_of(path)
    return int(times[-1, 1]) if times is not None and len(times) else 0


def _pieces_of(path: Path) -> list[Piece]:
    """A segment's pieces of sound at their moments; none when it keeps none, or
    cannot be read."""
    times = _times_of(path)
    if times is None or not len(times):
        return []
    by_pts = times[np.argsort(times[:, 0], kind="stable")]
    found: list[Piece] = []
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                return []
            audio = container.streams.audio[0]
            context = audio.codec_context
            form = Form(
                context.name,
                bytes(context.extradata or b""),
                int(context.sample_rate),
                context.layout.name,
            )
            for packet in container.demux(audio):
                if packet.pts is None or not packet.size:
                    continue
                pts = in_ms(packet.pts, fraction(packet.time_base))
                length = in_ms(packet.duration or 0, fraction(packet.time_base))
                near = int(np.searchsorted(by_pts[:, 0], pts))
                near = min(
                    range(max(near - 1, 0), min(near + 1, len(by_pts))),
                    key=lambda k: abs(int(by_pts[k, 0]) - pts),
                )
                ms = int(by_pts[near, 1]) + pts - int(by_pts[near, 0])
                found.append(Piece(ms, ms + max(length, 1), packet, form, path))
    except av.FFmpegError, OSError:
        return found  # what was read before the file gave out
    return found


class Renderer:
    """The sound from ``from_ms`` at ``rate`` -- forwards, x1/16 to x16 --, as
    interleaved 16-bit samples at ``out_rate`` in ``out_layout``, a piece at a time:
    a gap is silence of its length made SILENCE_MS at a time, never held whole."""

    def __init__(
        self,
        found: Iterator[Piece],
        from_ms: int,
        rate: float,
        out_rate: int = 48000,
        out_layout: str = "stereo",
    ) -> None:
        self.found, self.from_ms, self.rate = found, from_ms, rate
        self.out_rate, self.out_layout = out_rate, out_layout
        self._form: Form | None = None
        self._decoder: Any = None
        self._graph: av.filter.Graph | None = None
        self._next_ms: float = from_ms  # where the sound fed so far reaches, ms
        self._chunks = self._made()

    def read(self) -> bytes:
        """The samples of the next stretch; b"" once the sound has ended."""
        return next(self._chunks, b"")

    def _made(self) -> Iterator[bytes]:
        for piece in self.found:
            if piece.form != self._form:
                yield from _given(self._flush())  # what the former form left
                self._open(piece.form)
            yield from self._fed(piece)
        yield from _given(self._flush())

    def _fed(self, piece: Piece) -> Iterator[bytes]:
        """A piece decoded on its moment -- a segment's own timestamps go back at its
        start, and a decoder drops a piece whose time goes back --; a gap before what
        it gives made silence of its length, what comes before the moment asked
        dropped. A decoder gives nothing for the first piece it is given."""
        packet = piece.packet
        packet.pts = packet.dts = piece.ms
        packet.time_base = MS
        try:
            frames = self._decoder.decode(packet)
        except av.FFmpegError:  # damaged -- a crash's cut --: its length silence
            return
        for frame in frames:
            at = piece.ms if frame.pts is None else in_ms(frame.pts, fraction(MS))
            if at > self._next_ms + GAP_MS:  # a gap: silence of its length
                while (left := at - self._next_ms) > 0:
                    ms = min(left, SILENCE_MS)
                    yield from _given(self._push(_silence_like(frame, round(ms))))
                    self._next_ms += ms
            skip = round((self.from_ms - at) * frame.sample_rate / 1000)
            kept = _trimmed(frame, skip) if skip > 0 else frame
            if kept is not None:  # the piece begins before the moment asked
                yield from _given(self._push(kept))
            length = frame.samples * 1000 / frame.sample_rate
            self._next_ms = max(self._next_ms, at + length)

    def _open(self, form: Form) -> None:
        self._form = form
        self._decoder = av.CodecContext.create(form.codec, "r")
        if form.header:
            self._decoder.extradata = form.header
        self._graph = None  # made with the first frame's own format

    def _push(self, frame: av.AudioFrame) -> bytes:
        if self._graph is None:
            self._graph = tempo_graph(frame, self.rate, self.out_rate, self.out_layout)
        self._graph.push(frame)
        return _pulled(self._graph)

    def _flush(self) -> bytes:
        if self._graph is None:
            return b""
        self._graph.push(None)
        out = _pulled(self._graph)
        self._graph = None
        return out


def _given(chunk: bytes) -> Iterator[bytes]:
    """``chunk`` when it holds samples: an empty one would read as the end."""
    if chunk:
        yield chunk


def tempo_graph(
    frame: av.AudioFrame, rate: float, out_rate: int, out_layout: str
) -> av.filter.Graph:
    """A filter graph from ``frame``'s format to 16-bit samples at ``out_rate`` in
    ``out_layout``, at ``rate`` with the pitch kept: atempo chained, each within its
    best range."""
    graph = av.filter.Graph()
    nodes = [
        graph.add_abuffer(
            sample_rate=frame.sample_rate,
            format=frame.format.name,
            layout=frame.layout.name,
            time_base=Fraction(1, frame.sample_rate),
        )
    ]
    left = rate
    while left < ATEMPO_LEAST:
        nodes.append(graph.add("atempo", str(ATEMPO_LEAST)))
        left /= ATEMPO_LEAST
    while left > ATEMPO_MOST:
        nodes.append(graph.add("atempo", str(ATEMPO_MOST)))
        left /= ATEMPO_MOST
    if left != 1.0:
        nodes.append(graph.add("atempo", f"{left:g}"))
    form = f"sample_fmts=s16:sample_rates={out_rate}:channel_layouts={out_layout}"
    nodes.append(graph.add("aformat", form))
    nodes.append(graph.add("abuffersink"))
    graph.link_nodes(*nodes).configure()
    return graph


def _pulled(graph: av.filter.Graph) -> bytes:
    out = b""
    while True:
        try:
            frame = graph.pull()
        except av.BlockingIOError, av.EOFError:
            return out
        if isinstance(frame, av.AudioFrame):  # s16, interleaved: one plane
            out += bytes(frame.planes[0])[
                : frame.samples * 2 * frame.layout.nb_channels
            ]


def _per_sample(frame: av.AudioFrame) -> tuple[np.ndarray, int]:
    """The frame's samples as an array, and its columns a sample: one planar, its
    channels interleaved packed."""
    samples = frame.to_ndarray()
    return samples, samples.shape[1] // max(frame.samples, 1)


def _like(frame: av.AudioFrame, samples: np.ndarray) -> av.AudioFrame:
    made = av.AudioFrame.from_ndarray(
        np.ascontiguousarray(samples),
        format=frame.format.name,
        layout=frame.layout.name,
    )
    made.sample_rate = frame.sample_rate
    return made


def _silence_like(frame: av.AudioFrame, ms: int) -> av.AudioFrame:
    """``ms`` of silence in ``frame``'s format."""
    samples, per = _per_sample(frame)
    count = max(round(ms * frame.sample_rate / 1000), 1)
    return _like(frame, np.zeros((samples.shape[0], count * per), samples.dtype))


def _trimmed(frame: av.AudioFrame, skip: int) -> av.AudioFrame | None:
    """``frame`` without its first ``skip`` samples; None when it has no more."""
    if skip >= frame.samples:
        return None
    samples, per = _per_sample(frame)
    return _like(frame, samples[:, skip * per :])
