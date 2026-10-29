"""Tiny ONNX models made for the tests: they see what a test tells them to."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

SIZE = 64  # the models' input: a 64 x 64 picture
STRIDES = (8, 16, 32)


def raw_output(
    boxes: list[tuple[float, float, float, float, int, float]],
) -> np.ndarray:
    """YOLOX's raw output, before decoding, holding ``boxes``: centre x, centre y,
    width, height in input pixels, the COCO class and the score."""
    cells = sum((SIZE // s) ** 2 for s in STRIDES)
    raw = np.zeros((1, cells, 85), np.float32)
    raw[0, :, 2:4] = math.log(1 / 8)  # tiny boxes elsewhere, scored 0
    for n, (cx, cy, w, h, kind, score) in enumerate(boxes):
        column, row = int(cx // 8), int(cy // 8)
        cell = row * (SIZE // 8) + column + n * 0  # stride 8 cells come first
        raw[0, cell, :4] = (
            cx / 8 - column,
            cy / 8 - row,
            math.log(w / 8),
            math.log(h / 8),
        )
        raw[0, cell, 4] = 1.0
        raw[0, cell, 5 + kind] = score
    return raw


def constant_detector(
    path: Path,
    boxes: list[tuple[float, float, float, float, int, float]],
    inputs: list[int | str] | None = None,
    raw: np.ndarray | None = None,
) -> Path:
    """A detector that sees ``boxes`` in every picture, as YOLOX would give them;
    or that gives ``raw`` as it is."""
    raw = raw_output(boxes) if raw is None else raw
    shape = inputs or [1, 3, SIZE, SIZE]
    given = helper.make_tensor_value_info("images", TensorProto.FLOAT, shape)
    out = helper.make_tensor_value_info("output", TensorProto.FLOAT, list(raw.shape))
    seen = helper.make_node(
        "Constant", [], ["output"], value=numpy_helper.from_array(raw)
    )
    graph = helper.make_graph([seen], "constant_yolox", [given], [out])
    opsets = [helper.make_opsetid("", 13)]
    model = helper.make_model(graph, opset_imports=opsets, ir_version=10)
    onnx.save(model, str(path))
    return path
