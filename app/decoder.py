"""Decode a recorded frame: open its segment, seek to the keyframe before it and
decode forward. A request for a later frame of the same segment decodes on without
seeking, so stepping is cheap. Used from one worker thread at a time.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import av
from av.container import InputContainer


class Decoder:
    """Keeps the last segment open between requests."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._container: InputContainer | None = None
        self._frames: Iterator[av.VideoFrame] | None = None
        self._last = -1  # the timestamp last decoded

    def decode(self, path: Path, pts: int) -> av.VideoFrame | None:
        """The frame at ``pts`` in segment ``path``, or the first after it; None
        when the segment holds none from there."""
        if path != self._path or self._container is None:
            self.close()
            self._container = av.open(str(path))
            self._path = path
        if self._frames is None or pts <= self._last:
            stream = self._container.streams.video[0]
            self._container.seek(pts, stream=stream, backward=True, any_frame=False)
            self._frames = self._container.decode(stream)
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
