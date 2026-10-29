"""Riders found by a detection model the referee downloaded beforehand (002, FR-003).

The model is a YOLOX COCO detector exported to ONNX (``yolox_s.onnx``, Apache-2.0):
a frame letterboxed onto grey 114 in BGR, its raw output decoded on grids at
strides 8, 16 and 32 (the YOLOX demo's postprocess), persons and bicycles kept
above 0.4, overlaps over 0.45 suppressed. It runs on the CPU; nothing is fetched.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np
import onnxruntime

RIDERS = (0, 1)  # COCO's person and bicycle
SCORE = 0.4
OVERLAP = 0.45
STRIDES = (8, 16, 32)
_CLASSES = 80


class ModelError(Exception):
    """The model cannot be used: what the referee is told."""


@dataclass(frozen=True)
class Box:
    """A rider seen: corners in the picture's 0-1 coordinates, how sure, what."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    kind: int


class Detector:
    def __init__(self, path: Path) -> None:
        try:
            self.session = onnxruntime.InferenceSession(
                str(path), providers=["CPUExecutionProvider"]
            )
        except Exception as error:  # onnxruntime raises its own kinds
            raise ModelError(f"the model cannot be loaded: {error}") from error
        self.name = path.name
        given = self.session.get_inputs()[0]
        shape = given.shape
        if (
            len(shape) != 4
            or shape[1] != 3
            or not all(isinstance(side, int) for side in shape[2:])
        ):
            raise ModelError("the model does not take a picture of a fixed size")
        self.input, self.height, self.width = given.name, int(shape[2]), int(shape[3])
        cells = sum((self.height // s) * (self.width // s) for s in STRIDES)
        out = self.session.get_outputs()[0].shape
        if len(out) != 3 or out[1] not in (cells, None) or out[2] not in (85, None):
            raise ModelError("the model is not a YOLOX detector of the 80 COCO classes")

    def riders(self, frame: av.VideoFrame) -> list[Box]:
        """The persons and bicycles in the frame."""
        picture, ratio = self._letterbox(frame)
        (raw,) = self.session.run(None, {self.input: picture})[:1]
        found = decode(np.asarray(raw, np.float32)[0], self.height, self.width)
        return riders(found, ratio, frame.width, frame.height)

    def _letterbox(self, frame: av.VideoFrame) -> tuple[np.ndarray, float]:
        ratio = min(self.height / frame.height, self.width / frame.width)
        width, height = (
            max(round(frame.width * ratio), 1),
            max(round(frame.height * ratio), 1),
        )
        resized = frame.reformat(
            width=width, height=height, format="bgr24"
        ).to_ndarray()
        padded = np.full((self.height, self.width, 3), 114, np.uint8)
        padded[:height, :width] = resized
        return padded.transpose(2, 0, 1)[None].astype(np.float32), ratio


def decode(raw: np.ndarray, height: int, width: int) -> np.ndarray:
    """YOLOX's raw boxes on the input's pixels: centres from grid offsets, sizes
    from their logarithms; scores as they are."""
    grid, step = _grid(height, width)
    found = raw.copy()
    found[:, :2] = (found[:, :2] + grid) * step
    found[:, 2:4] = np.exp(found[:, 2:4]) * step
    return found


@functools.cache
def _grid(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    """Each cell's column and row on the three grids, and its stride: the same for
    every frame of a model, so made once."""
    grids, steps = [], []
    for stride in STRIDES:
        rows, columns = np.meshgrid(
            np.arange(height // stride), np.arange(width // stride), indexing="ij"
        )
        grids.append(np.stack([columns.ravel(), rows.ravel()], axis=1))
        steps.append(np.full((rows.size, 1), stride))
    return np.concatenate(grids), np.concatenate(steps)


def riders(found: np.ndarray, ratio: float, width: int, height: int) -> list[Box]:
    """Persons and bicycles sure enough, one box each, in 0-1 picture coordinates."""
    scores = found[:, 4:5] * found[:, 5 : 5 + _CLASSES]
    kinds = scores[:, list(RIDERS)].argmax(axis=1)
    best = scores[np.arange(len(found)), np.asarray(RIDERS)[kinds]]
    keep = best >= SCORE
    centres, sizes = found[keep, :2] / ratio, found[keep, 2:4] / ratio
    corners = np.concatenate([centres - sizes / 2, centres + sizes / 2], axis=1)
    chosen = suppress(corners, best[keep])
    scale = np.array([width, height, width, height], np.float32)
    boxes = []
    for i in chosen:
        x1, y1, x2, y2 = np.clip(corners[i] / scale, 0, 1)
        boxes.append(
            Box(
                float(x1),
                float(y1),
                float(x2),
                float(y2),
                float(best[keep][i]),
                RIDERS[int(kinds[keep][i])],
            )
        )
    return boxes


def suppress(corners: np.ndarray, scores: np.ndarray) -> list[int]:
    """The boxes kept, surest first, dropping each that overlaps a kept one more
    than OVERLAP."""
    order = list(np.argsort(-scores, kind="stable"))
    kept: list[int] = []
    while order:
        i = order.pop(0)
        kept.append(int(i))
        order = [j for j in order if iou(corners[i], corners[j]) <= OVERLAP]
    return kept


def iou(a: np.ndarray, b: np.ndarray) -> float:
    """How much two boxes overlap: their intersection over their union."""
    width = max(min(a[2], b[2]) - max(a[0], b[0]), 0)
    height = max(min(a[3], b[3]) - max(a[1], b[1]), 0)
    common = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - common
    return float(common / union) if union > 0 else 0.0
