"""Riders' numbers read by the two models, on fakes of them (specs/006)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper

from app.analysis import numbers
from app.analysis.numbers import NumberReader, crop, ctc, grown, pieces

DIGITS = list("0123456789")


def classes(line: list[int], sure: float = 0.99) -> np.ndarray:
    """The reader's output for a line: each step's class certain to ``sure``."""
    probs = np.full((len(line), len(DIGITS) + 2), (1 - sure) / (len(DIGITS) + 1))
    for step, kind in enumerate(line):
        probs[step, kind] = sure
    return probs


def test_the_finder_s_map_is_parted_into_pieces_and_specks_left_out() -> None:
    marked = np.zeros((40, 80), dtype=bool)
    marked[10:15, 20:30] = True  # 50 pixels: text
    marked[30:33, 60:63] = True  # 9: a speck
    marked[11, 31] = True  # not touching side by side: a speck of its own
    assert pieces(marked) == [(10, 20, 15, 30)]


def test_a_piece_grows_as_db_unclips_it_into_the_picture_s_pixels() -> None:
    # 10 by 40: pad 400 x 1.5 / 100 = 6; the map at half the picture's size.
    assert grown((10, 20, 20, 60), (2.0, 2.0), (100, 200)) == (8, 28, 52, 132)
    assert grown((0, 0, 10, 40), (2.0, 2.0), (30, 70)) == (0, 0, 30, 70)  # inside it


def test_a_line_read_keeps_repeats_once_and_leaves_blanks_out() -> None:
    text, sure = ctc(classes([0, 3, 3, 0, 5, 8, 8, 0, 3]), DIGITS)
    assert text == "2472"
    assert sure == pytest.approx(0.99)
    assert ctc(classes([0, 0]), DIGITS) == ("", 0.0)
    assert ctc(classes([11]), DIGITS)[0] == " "  # past the characters: the space


def test_a_rider_s_box_is_cropped_with_a_margin() -> None:
    rgb = np.zeros((100, 200, 3), np.uint8)
    box = SimpleNamespace(x1=0.25, y1=0.5, x2=0.75, y2=1.0)
    assert crop(rgb, box).shape == (55, 120, 3)


def reader(lines: list[tuple[list[int], float]], marks: list[slice]) -> NumberReader:
    """A reader whose finder marks ``marks``, whose reader reads ``lines`` in turn."""
    made = NumberReader.__new__(NumberReader)

    def find(_: Any, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        _, _, high, wide = feed["x"].shape
        found = np.zeros((1, 1, high, wide), np.float32)
        for rows in marks:
            found[0, 0, rows, 2 : wide - 2] = 0.9
        return [found]

    read = iter(lines)

    def look(_: Any, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        line, sure = next(read)
        return [classes(line, sure)[None]]

    made.finder = SimpleNamespace(run=find)  # type: ignore[assignment]
    made.reader = SimpleNamespace(run=look)  # type: ignore[assignment]
    made.chars = DIGITS
    return made


def test_the_number_is_the_most_confident_reading_s_digits() -> None:
    rgb = np.full((96, 128, 3), 200, np.uint8)
    two = [slice(4, 12), slice(40, 48)]
    found = reader([([2, 9], 0.85), ([11, 3, 8], 0.97)], two).read(rgb)
    assert found is not None
    assert found[0] == "27"  # the space read dropped: digits only
    assert found[1] == pytest.approx(0.97)


def test_no_number_from_an_unsure_reading_or_no_text() -> None:
    rgb = np.full((96, 128, 3), 200, np.uint8)
    assert reader([([2, 9], 0.5)], [slice(4, 12)]).read(rgb) is None
    assert reader([], []).read(rgb) is None
    assert reader([([11], 0.99)], [slice(4, 12)]).read(rgb) is None  # no digit


def test_a_picture_with_no_extent_reads_nothing() -> None:
    made = reader([], [])
    assert made.line(np.zeros((0, 5, 3), np.uint8)) == ("", 0.0)


def test_pictures_are_scaled_by_ffmpeg() -> None:
    rgb = np.full((10, 20, 3), 100, np.uint8)
    assert numbers.scale(rgb, 40, 32).shape == (32, 40, 3)


def tiny_models(folder: Path) -> tuple[Path, Path]:
    """A finder that marks a bright picture whole, and a reader that always reads
    42, its characters in its metadata as PaddleOCR's own."""
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, None, None])
    found = helper.make_tensor_value_info("map", TensorProto.FLOAT, [1, 1, None, None])
    mean = helper.make_node("ReduceMean", ["x"], ["map"], axes=[1], keepdims=1)
    finder = helper.make_model(
        helper.make_graph([mean], "finder", [x], [found]),
        opset_imports=[helper.make_opsetid("", 13)],
    )
    probs = classes([0, 5, 0, 3, 0])[None].astype(np.float32)
    line = helper.make_tensor_value_info("line", TensorProto.FLOAT, list(probs.shape))
    constant = helper.make_node(
        "Constant", [], ["line"], value=numpy_helper.from_array(probs)
    )
    reader = helper.make_model(
        helper.make_graph([constant], "reader", [x], [line]),
        opset_imports=[helper.make_opsetid("", 13)],
    )
    helper.set_model_props(reader, {"character": "\n".join(DIGITS)})
    paths = folder / "finder.onnx", folder / "reader.onnx"
    for model, path in zip((finder, reader), paths, strict=True):
        model.ir_version = 8
        onnx.save(model, path)
    return paths


def test_the_reader_loads_its_two_models_and_reads_with_them(tmp_path: Path) -> None:
    made = NumberReader(*tiny_models(tmp_path))
    assert made.chars == DIGITS
    found = made.read(np.full((60, 90, 3), 230, np.uint8))
    assert found is not None
    assert found[0] == "42"


def test_the_models_are_given_bgr_as_paddleocr_trained_them() -> None:
    made = reader([], [])
    given: list[np.ndarray] = []

    def find(_: Any, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        given.append(feed["x"])
        return [np.zeros((1, 1, *feed["x"].shape[2:]), np.float32)]

    made.finder = SimpleNamespace(run=find)  # type: ignore[assignment]
    red = np.zeros((32, 32, 3), np.uint8)
    red[..., 0] = 255
    assert made.read(red) is None
    channels = given[0][0].mean(axis=(1, 2))
    assert channels[0] == pytest.approx((0 - 0.485) / 0.229, abs=0.05)  # blue first
    assert channels[2] == pytest.approx((1 - 0.406) / 0.225, abs=0.05)  # red last
