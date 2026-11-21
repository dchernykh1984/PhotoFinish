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
import itertools
from collections.abc import Iterator
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import numpy as np

from app.recorder.segments import LEAD_MS, fraction, in_ms
from app.video_index import VideoIndex, read_times

GAP_MS = 30  # a piece this much after the end of the one before: silence between
PREROLL_MS = 50  # decoded before the moment asked and dropped: no click as it begins
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


def has_sound(path: Path) -> bool:
    """Whether a segment keeps sound beside its frames."""
    try:
        with av.open(str(path)) as container:
            return bool(container.streams.audio)
    except av.FFmpegError, OSError:
        return False


def pieces(index: VideoIndex, from_ms: int) -> Iterator[Piece]:
    """The camera's pieces of sound from ``from_ms`` on its own times, in order, each
    once -- and the one before it, PREROLL_MS, for a decoder to begin on --: from the
    segment before the one of the frame at ``from_ms``, whose sound may reach past
    its end."""
    place = index.at_or_before(from_ms)
    if place is None:
        return
    found = index.segments_from(place)
    held: list[Piece] = []
    last_end: int | None = None
    for path, after in itertools.zip_longest(found, found[1:]):
        held.extend(_pieces_of(path))
        heapq.heapify(held)
        # A piece of the next segment comes LEAD_MS before its first frame at most.
        safe = _first_ms(after) - LEAD_MS if after is not None else None
        while held and (safe is None or held[0].ms < safe):
            piece = heapq.heappop(held)
            if piece.end_ms <= from_ms - PREROLL_MS:
                continue  # before the moment asked
            if last_end is not None and piece.ms < last_end - _half(piece):
                continue  # heard already: sent again, or kept by a run before
            last_end = piece.end_ms
            yield piece


def _half(piece: Piece) -> int:
    return (piece.end_ms - piece.ms) // 2


def _first_ms(path: Path) -> int:
    times = read_times(path)
    return int(times[0, 1]) if times is not None and len(times) else 0


def _pieces_of(path: Path) -> list[Piece]:
    """A segment's pieces of sound at their moments; none when it keeps none, or
    cannot be read."""
    times = read_times(path)
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
                found.append(Piece(ms, ms + max(length, 1), packet, form))
    except av.FFmpegError, OSError:
        return found  # what was read before the file gave out
    return found


class Renderer:
    """The sound from ``from_ms`` at ``rate`` -- forwards, x1/16 to x16 --, as
    interleaved 16-bit samples at ``out_rate`` in ``out_layout``, piece by piece."""

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
        self.ended = False

    def read(self) -> bytes:
        """The samples of the next piece -- after silence for a gap before it --; b""
        once the sound has ended, the graph's last samples given before."""
        for piece in self.found:
            out = self._feed(piece)
            if out:
                return out
        if not self.ended:
            self.ended = True
            return self._flush()
        return b""

    def _feed(self, piece: Piece) -> bytes:
        if piece.form != self._form:
            out = self._flush()  # what the former form left
            self._open(piece.form)
            return out + self._feed_piece(piece)
        return self._feed_piece(piece)

    def _feed_piece(self, piece: Piece) -> bytes:
        """A piece decoded on its moment -- a segment's own timestamps go back at its
        start, and a decoder drops a piece whose time goes back --; a gap before what
        it gives made silence of its length, what comes before the moment asked
        dropped. A decoder gives nothing for the first piece it is given."""
        packet = piece.packet
        packet.pts = packet.dts = piece.ms
        packet.time_base = MS
        out = b""
        for frame in self._decoder.decode(packet):
            at = piece.ms if frame.pts is None else in_ms(frame.pts, fraction(MS))
            if at > self._next_ms + GAP_MS:
                out += self._push(_silence_like(frame, round(at - self._next_ms)))
            skip = round((self.from_ms - at) * frame.sample_rate / 1000)
            kept = _trimmed(frame, skip) if skip > 0 else frame
            if kept is not None:
                out += self._push(kept)
            self._next_ms = max(
                self._next_ms, at + frame.samples * 1000 / frame.sample_rate
            )
        return out

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
