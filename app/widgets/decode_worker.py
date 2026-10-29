"""Frames decoded on a thread of their own; the newest request wins.

The window asks for a frame by segment and timestamp with a tag of its own; the
answer comes back as a signal with the tag and a QImage (null when there was no such
frame). A request made while another is decoding replaces any not yet started, so
scrolling never queues up work.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import av
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImage

from app.decoder import Decoder


class DecodeWorker(QObject):
    decoded = Signal(object, QImage)  # the request's tag, the frame
    _poke = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._wanted: tuple[Path, int, Any] | None = None
        self._decoder = Decoder()
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._poke.connect(self._work)
        self._thread.start()

    def request(self, path: Path, pts: int, tag: Any) -> None:
        with self._lock:
            self._wanted = (path, pts, tag)
        self._poke.emit()

    def stop(self) -> None:
        self._thread.quit()
        self._thread.wait()
        self._decoder.close()

    @Slot()
    def _work(self) -> None:
        with self._lock:
            wanted, self._wanted = self._wanted, None
        if wanted is None:
            return  # a later poke took it
        path, pts, tag = wanted
        try:
            frame = self._decoder.decode(path, pts)
            image = QImage() if frame is None else to_qimage(frame)
        except Exception:  # whatever keeps a frame from the view: answered, never left
            self._decoder.close()  # the next segment may be read
            image = QImage()
        self.decoded.emit(tag, image)


def to_qimage(frame: av.VideoFrame) -> QImage:
    """The frame as an RGB image that owns its pixels. Rows padded for alignment
    (a width such as 1366) are packed first: the image reads them packed."""
    pixels = np.ascontiguousarray(frame.to_ndarray(format="rgb24"))
    height, width = pixels.shape[:2]
    image = QImage(pixels.data, width, height, 3 * width, QImage.Format.Format_RGB888)
    return image.copy()
