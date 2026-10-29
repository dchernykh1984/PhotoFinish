"""Riders found by a local YOLOX model: decoding, filtering, loading (002 FR-003)."""

from __future__ import annotations

import json
from pathlib import Path

import av
import numpy as np
import pytest

from app import paths, session
from app.analysis import analyzer
from app.analysis.detector import (
    Detector,
    ModelError,
    decode,
    iou,
    riders,
    suppress,
)
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import render
from tests.onnx_models import SIZE, constant_detector, raw_output

PERSON, BICYCLE, CAR = 0, 1, 2


def test_raw_boxes_are_decoded_on_their_grid() -> None:
    raw = raw_output([(20.0, 36.0, 16.0, 40.0, PERSON, 0.9)])[0]
    found = decode(raw, SIZE, SIZE)
    row = found[(36 // 8) * (SIZE // 8) + 20 // 8]
    assert row[:4] == pytest.approx([20.0, 36.0, 16.0, 40.0])
    assert row[4] == 1.0
    assert row[5 + PERSON] == pytest.approx(0.9)


def test_persons_and_bicycles_sure_enough_are_kept_once_each() -> None:
    raw = raw_output(
        [
            (20.0, 36.0, 16.0, 40.0, PERSON, 0.9),
            (52.0, 36.0, 8.0, 8.0, BICYCLE, 0.5),
            (40.0, 10.0, 8.0, 8.0, CAR, 0.99),  # no rider
            (12.0, 52.0, 8.0, 8.0, PERSON, 0.3),  # not sure enough
        ]
    )[0]
    found = riders(decode(raw, SIZE, SIZE), 0.1, 640, 360)
    assert [(b.kind, round(b.score, 2)) for b in found] == [
        (PERSON, 0.9),
        (BICYCLE, 0.5),
    ]
    person = found[0]
    assert (person.x1, person.y1) == pytest.approx((120 / 640, 160 / 360))
    assert (person.x2, person.y2) == pytest.approx((280 / 640, 1.0))  # clipped


def test_overlapping_boxes_keep_the_surest() -> None:
    corners = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [20, 20, 30, 30]], np.float32)
    assert suppress(corners, np.array([0.5, 0.9, 0.7])) == [1, 2]
    assert iou(corners[0], corners[2]) == 0.0
    assert iou(corners[0], corners[0]) == 1.0
    assert iou(np.zeros(4), np.zeros(4)) == 0.0


def test_a_model_sees_riders_in_a_frame(tmp_path: Path) -> None:
    model = constant_detector(
        tmp_path / "yolox.onnx", [(32.0, 20.0, 16.0, 16.0, PERSON, 0.8)]
    )
    detector = Detector(model)
    assert (detector.name, detector.height, detector.width) == (
        "yolox.onnx",
        SIZE,
        SIZE,
    )
    frame = av.VideoFrame.from_ndarray(render(0, 640, 360), format="rgb24")
    (box,) = detector.riders(frame)
    corners = (box.x1, box.y1, box.x2, box.y2)
    assert corners == pytest.approx((240 / 640, 120 / 360, 400 / 640, 280 / 360))
    assert (box.score, box.kind) == (pytest.approx(0.8), PERSON)


@pytest.mark.parametrize(
    ("inputs", "raw", "said"),
    [
        (["n", 3, "h", "w"], None, "fixed size"),
        ([1, 3, SIZE], None, "fixed size"),
        (None, np.zeros((1, 84, 6), np.float32), "YOLOX detector"),
        (None, np.zeros((1, 85), np.float32), "YOLOX detector"),
    ],
)
def test_a_model_that_is_no_yolox_detector_is_refused(
    tmp_path: Path, inputs: list | None, raw: np.ndarray | None, said: str
) -> None:
    model = constant_detector(tmp_path / "x.onnx", [], inputs=inputs, raw=raw)
    with pytest.raises(ModelError, match=said):
        Detector(model)


def test_a_file_that_is_no_model_is_refused(tmp_path: Path) -> None:
    junk = tmp_path / "junk.onnx"
    junk.write_bytes(b"not a model")
    with pytest.raises(ModelError, match="cannot be loaded"):
        Detector(junk)


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    return tmp_path


def test_with_a_model_the_index_is_where_it_sees_riders_in_the_zone(base: Path) -> None:
    model = constant_detector(
        base / "yolox.onnx", [(32.0, 20.0, 16.0, 16.0, PERSON, 0.8)]
    )
    aside = constant_detector(base / "aside.onnx", [(4.0, 4.0, 4.0, 4.0, PERSON, 0.8)])
    for chosen, expected in ((model, 1), (aside, 0)):
        camera = {"id": "cam1", "connection": "test", "settings": {"fps": 10}}
        analysis = {"on": True, "model": chosen.name}
        session.save({**session.DEFAULTS, "cameras": [camera], "analysis": analysis})
        folder = base / "video" / "cam1"
        for old in folder.glob("*"):
            old.unlink()
        writer = SegmentWriter(folder, fps=10)
        for k in range(15):
            writer.write(render(1_000_000 + k * 100, 640, 360), 1_000_000 + k * 100)
        writer.close()
        assert analyzer.run("cam1", stop=lambda: False, once=True) == 0
        lines = (folder / "activity.jsonl").read_text().splitlines()
        activity = [json.loads(line) for line in lines]
        assert {a["method"] for a in activity} == {f"model:{chosen.name}"}
        found = [s for a in activity for s in a["stretches"]]
        assert len(found) == expected * len(activity)


def test_a_model_that_cannot_be_used_stops_the_analysis_and_says_why(
    base: Path,
) -> None:
    (base / "junk.onnx").write_bytes(b"not a model")
    camera = {"id": "cam1", "connection": "test"}
    analysis = {"on": True, "model": "junk.onnx"}
    session.save({**session.DEFAULTS, "cameras": [camera], "analysis": analysis})
    (base / "video" / "cam1").mkdir(parents=True)
    assert analyzer.run("cam1", stop=lambda: False, once=True) == 2
    progress = json.loads((base / "video" / "cam1" / "analyzer.json").read_text())
    assert progress["state"] == "failed"
    assert progress["detail"].startswith("the model cannot be loaded")
