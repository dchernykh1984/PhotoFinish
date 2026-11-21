"""Decode a recorded frame: open its segment, seek to the keyframe before it and
decode forward. A request for a frame a little later in the same file decodes on
without seeking, so stepping is cheap; one more than FAR_S later -- in a camera's own
long recording -- seeks. The frames decoded lately are kept, up to KEEP_BYTES: a step
back, or playing backwards, takes them from there, each stretch between two keyframes
decoded about once (specs/012, FR-005). Used from one worker thread at a time.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path

import av
from av.container import InputContainer

FAR_S = 2.0  # further ahead than this, seeking beats decoding every frame between
# Some 17 frames of 1440p, 30 of 1080p, a camera: a stretch to step back over without
# a decode from its keyframe, and room for a few cameras' on a laptop.
KEEP_BYTES = 96 << 20


class Decoder:
    """Keeps the last segment open between requests, and its frames decoded lately."""

    def __init__(self, keep_bytes: int = KEEP_BYTES) -> None:
        self._path: Path | None = None
        self._container: InputContainer | None = None
        self._frames: Iterator[av.VideoFrame] | None = None
        self._last = -1  # the timestamp last decoded
        self.seeks = 0
        self._keep_bytes = keep_bytes
        self._kept: OrderedDict[int, tuple[av.VideoFrame, int]] = OrderedDict()
        self._kept_bytes = 0

    @property
    def kept(self) -> int:
        """How many frames are kept."""
        return len(self._kept)

    def decode(self, path: Path, pts: int) -> av.VideoFrame | None:
        """The frame at ``pts`` in segment ``path``, or the first after it; None
        when the segment holds none from there."""
        if path != self._path or self._container is None:
            self.close()
            self._container = av.open(str(path))
            self._path = path
        if (kept := self._kept.get(pts)) is not None:
            return kept[0]
        stream = self._container.streams.video[0]
        rate = stream.time_base
        far = FAR_S * rate.denominator / rate.numerator if rate else FAR_S * 1000
        if self._frames is None or pts <= self._last or pts - self._last > far:
            self._container.seek(pts, stream=stream, backward=True, any_frame=False)
            self._frames = self._container.decode(stream)
            self.seeks += 1
        for frame in self._frames:
            if frame.pts is None:
                continue
            self._last = frame.pts
            self._keep(frame, frame.pts)
            if frame.pts >= pts:
                return frame
        self._frames = None
        return None

    def _keep(self, frame: av.VideoFrame, pts: int) -> None:
        """``frame`` kept, the oldest kept let go past KEEP_BYTES; the newest stays."""
        size = sum(plane.buffer_size for plane in frame.planes)
        if (old := self._kept.pop(pts, None)) is not None:
            self._kept_bytes -= old[1]
        self._kept[pts] = (frame, size)
        self._kept_bytes += size
        while self._kept_bytes > self._keep_bytes and len(self._kept) > 1:
            _, (_, gone) = self._kept.popitem(last=False)
            self._kept_bytes -= gone

    def close(self) -> None:
        if self._container is not None:
            self._container.close()
        self._path, self._container, self._frames, self._last = None, None, None, -1
        self._kept.clear()
        self._kept_bytes = 0
