"""The test camera: synthetic frames that carry their own time.

Every frame shows its moment as a clock the referee reads and as a strip of black
and white blocks along the bottom that a test reads back after encoding. Scenes add
a bar crossing the frame once a second (sub-frame timing), a flash for the first
100 ms of every 5 s (aligning two cameras) or a swaying patch (motion).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator

import numpy as np

SCENES = ("clock", "bar", "flash", "sway")
_BITS = 44  # Unix milliseconds until the year 2527
_STRIP = 16  # the strip's height in pixels
_FONT = {  # 3 x 5 glyphs, rows top to bottom
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    ":": ("000", "010", "000", "010", "000"),
    ".": ("000", "000", "000", "000", "010"),
}
_GLYPHS = {
    char: np.array([[bit == "1" for bit in row] for row in rows])
    for char, rows in _FONT.items()
}


def render(ms: int, width: int, height: int, scene: str = "clock") -> np.ndarray:
    """The frame of moment ``ms`` (Unix ms): ``height`` x ``width`` x RGB."""
    image = np.full((height, width, 3), 64, np.uint8)
    if scene == "flash" and ms % 5000 < 100:
        image[:] = 255
    elif scene == "bar":
        x = ms * width // 1000 % width  # the leading edge crosses once a second
        image[:, max(x - width // 40, 0) : x] = 255
    elif scene == "sway":
        side = height // 4
        x = int(width / 2 + width / 4 * math.sin(2 * math.pi * ms / 2000))
        image[height // 3 : height // 3 + side, x - side // 2 : x + side // 2] = 200
    _draw_clock(image, ms)
    _draw_strip(image, ms)
    return image


def read_time(image: np.ndarray) -> int:
    """The moment a frame's strip holds, read back from a decoded frame."""
    height, width = image.shape[:2]
    block = width // _BITS
    row = image[height - _STRIP // 2].mean(axis=1)
    centres = row[block // 2 :: block][:_BITS]
    return sum(int(value > 127) << (_BITS - 1 - i) for i, value in enumerate(centres))


def _draw_clock(image: np.ndarray, ms: int) -> None:
    moment = time.localtime(ms / 1000)
    text = time.strftime("%H:%M:%S", moment) + f".{ms % 1000:03d}"
    scale = max(image.shape[0] // 60, 1)
    x = y = 2 * scale
    for char in text:
        glyph = np.kron(_GLYPHS[char], np.ones((scale, scale), bool))
        image[y : y + glyph.shape[0], x : x + glyph.shape[1]][glyph] = 255
        x += 4 * scale


def _draw_strip(image: np.ndarray, ms: int) -> None:
    height, width = image.shape[:2]
    bits = (ms >> np.arange(_BITS - 1, -1, -1)) & 1
    row = np.repeat(bits * 255, width // _BITS).astype(np.uint8)
    image[height - _STRIP :, : row.size] = row[None, :, None]


class TestCamera:
    """Frames at a steady rate, each at its moment on ``clock`` (Unix ms)."""

    __test__ = False  # a camera, not a pytest class

    def __init__(
        self,
        fps: float = 30,
        width: int = 640,
        height: int = 360,
        scene: str = "clock",
        clock: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if scene not in SCENES:
            raise ValueError(f"unknown scene {scene!r}")
        self.fps, self.width, self.height, self.scene = fps, width, height, scene
        self.clock, self.sleep = clock, sleep

    def frames(self) -> Iterator[tuple[np.ndarray, int]]:
        """Frames without end, each with its moment. A frame whose moment passed while
        the last one was being taken is dropped, as a camera would."""
        start, k = self.clock(), 0
        while True:
            due = start + round(k * 1000 / self.fps)
            now = self.clock()
            if now < due:
                self.sleep((due - now) / 1000)
            elif now - due >= 1000 / self.fps:
                k = int((now - start) * self.fps / 1000)
                continue
            yield render(due, self.width, self.height, self.scene), due
            k += 1
