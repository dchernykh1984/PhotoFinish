"""Riders' numbers read at their crossings (specs/006, FR-002).

Two ONNX models, PaddleOCR's PP-OCRv3 English text finder (DB) and reader (CTC):
the finder marks where text is in the rider's box, each mark is read, and the
digits of the most confident reading are the number. No OpenCV (002): the
finder's map is parted into its pieces by a flood fill over its few marked
pixels, and pictures are scaled by FFmpeg.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import av
import numpy as np
import onnxruntime

LEAST_CONFIDENCE = 0.8  # a reading less sure than this names no number
MARKED = 0.3  # the finder's map: text from here up
LEAST_PIXELS = 20  # of the finder's map: a piece smaller is noise
GROWN = 1.5  # a piece grown as DB's unclip grows it: area x this / perimeter
SIDE = 32  # the finder takes sides in multiples of this
LARGEST = 640  # nor longer than this, so a box is read in a moment
HEIGHT, WIDEST = 48, 320  # the reader's line
MEAN = np.array([0.485, 0.456, 0.406])
STD = np.array([0.229, 0.224, 0.225])

type Piece = tuple[int, int, int, int]  # top, left, bottom, right


class NumberReader:
    """The two models, loaded once; ``read`` gives the number in a rider's box."""

    def __init__(self, finder: Path, reader: Path) -> None:
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1  # beside the recorder, never before it
        cpu = ["CPUExecutionProvider"]
        self.finder = onnxruntime.InferenceSession(str(finder), options, providers=cpu)
        self.reader = onnxruntime.InferenceSession(str(reader), options, providers=cpu)
        meta = self.reader.get_modelmeta().custom_metadata_map
        self.chars = str(meta.get("character", "")).split("\n")

    def read(self, rgb: np.ndarray) -> tuple[str, float] | None:
        """The digits most confidently read in a picture, with how sure; None when
        none is read with LEAST_CONFIDENCE."""
        best: tuple[str, float] | None = None
        for top, left, bottom, right in self.texts(rgb):
            text, sure = self.line(rgb[top:bottom, left:right])
            digits = "".join(c for c in text if c.isdigit())
            if digits and sure >= LEAST_CONFIDENCE and (best is None or sure > best[1]):
                best = digits, sure
        return best

    def texts(self, rgb: np.ndarray) -> list[Piece]:
        """Where the finder sees text, in the picture's pixels."""
        height, width = rgb.shape[:2]
        size = min(1.0, LARGEST / max(height, width))
        high = max(SIDE, round(height * size / SIDE) * SIDE)
        wide = max(SIDE, round(width * size / SIDE) * SIDE)
        scaled = scale(rgb, wide, high) / 255.0
        x = ((scaled - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
        marked = self.finder.run(None, {"x": x})[0][0, 0] > MARKED
        return [
            grown(piece, (height / high, width / wide), (height, width))
            for piece in pieces(marked)
        ]

    def line(self, rgb: np.ndarray) -> tuple[str, float]:
        """A line of text read, with how sure the reader is of it."""
        height, width = rgb.shape[:2]
        if not height or not width:
            return "", 0.0
        wide = max(16, min(WIDEST, round(width * HEIGHT / height)))
        scaled = scale(rgb, wide, HEIGHT) / 255.0
        x = ((scaled - 0.5) / 0.5).transpose(2, 0, 1)[None].astype(np.float32)
        return ctc(self.reader.run(None, {"x": x})[0][0], self.chars)


def scale(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """The picture at another size, scaled by FFmpeg."""
    frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
    return frame.reformat(width=width, height=height).to_ndarray()


def pieces(marked: np.ndarray) -> list[Piece]:
    """The bounds of each piece of marked pixels touching side by side, the small
    ones left out."""
    seen = np.zeros_like(marked, dtype=bool)
    rows, cols = marked.shape
    found = []
    for y, x in zip(*np.nonzero(marked), strict=True):
        if seen[y, x]:
            continue
        seen[y, x] = True
        stack, ys, xs = [(int(y), int(x))], [], []
        while stack:
            cy, cx = stack.pop()
            ys.append(cy)
            xs.append(cx)
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < rows and 0 <= nx < cols and marked[ny, nx]:
                    if not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        if len(ys) >= LEAST_PIXELS:
            found.append((min(ys), min(xs), max(ys) + 1, max(xs) + 1))
    return found


def grown(piece: Piece, step: tuple[float, float], size: tuple[int, int]) -> Piece:
    """A piece of the finder's map grown as DB's unclip grows it -- its marks are
    the text's core -- in the picture's pixels."""
    top, left, bottom, right = piece
    area, perimeter = (bottom - top) * (right - left), 2 * (bottom - top + right - left)
    pad = area * GROWN / perimeter
    (dy, dx), (height, width) = step, size
    return (
        max(0, int((top - pad) * dy)),
        max(0, int((left - pad) * dx)),
        min(height, int((bottom + pad) * dy)),
        min(width, int((right + pad) * dx)),
    )


def ctc(probs: np.ndarray, chars: Sequence[str]) -> tuple[str, float]:
    """A line from the reader's classes at each step: repeats once, blanks (0) left
    out; how sure, the mean of the classes kept."""
    best, sure = probs.argmax(axis=1), probs.max(axis=1)
    text, kept, previous = [], [], 0
    for kind, how in zip(best.tolist(), sure.tolist(), strict=True):
        if kind and kind != previous:
            text.append(chars[kind - 1] if kind - 1 < len(chars) else " ")
            kept.append(how)
        previous = kind
    return "".join(text), float(np.mean(kept)) if kept else 0.0


def crop(rgb: np.ndarray, box: Any, margin: float = 0.1) -> np.ndarray:
    """A rider's box in a picture, ``box`` in 0-1 coordinates, a margin around."""
    height, width = rgb.shape[:2]
    pad_x, pad_y = (box.x2 - box.x1) * margin, (box.y2 - box.y1) * margin
    left, right = max(0.0, box.x1 - pad_x), min(1.0, box.x2 + pad_x)
    top, bottom = max(0.0, box.y1 - pad_y), min(1.0, box.y2 + pad_y)
    return rgb[
        int(top * height) : int(bottom * height), int(left * width) : int(right * width)
    ]
