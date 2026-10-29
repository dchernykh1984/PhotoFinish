"""Decode a recorded frame: open its segment, seek to the keyframe before it and
decode forward. A request for a frame a little later in the same file decodes on
without seeking, so stepping is cheap; one more than FAR_S later -- in a camera's own
long recording -- seeks. Used from one worker thread at a time.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import av
from av.container import InputContainer

FAR_S = 2.0  # further ahead than this, seeking beats decoding every frame between


class Decoder:
    """Keeps the last segment open between requests."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._container: InputContainer | None = None
        self._frames: Iterator[av.VideoFrame] | None = None
        self._last = -1  # the timestamp last decoded
        self.seeks = 0

    def decode(self, path: Path, pts: int) -> av.VideoFrame | None:
        """The frame at ``pts`` in segment ``path``, or the first after it; None
        when the segment holds none from there."""
        if path != self._path or self._container is None:
            self.close()
            self._container = av.open(str(path))
            self._path = path
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
            if frame.pts >= pts:
                return frame
        self._frames = None
        return None

    def close(self) -> None:
        if self._container is not None:
            self._container.close()
        self._path, self._container, self._frames, self._last = None, None, None, -1
