"""Camera connections opened as sources of frames."""

from __future__ import annotations

import numpy as np
import pytest

from app.recorder.sources import CameraSettingsError, open_source

START = 1_761_716_129_587


def test_a_test_camera_opens_with_its_settings() -> None:
    camera = {"connection": "test", "settings": {"fps": 60, "scene": "bar"}}
    source = open_source(camera, clock=lambda: START)
    assert source.fps == 60
    image, ms = next(source.frames())
    assert isinstance(image, np.ndarray)
    assert (image.shape, ms) == ((360, 640, 3), START)


@pytest.mark.parametrize(
    "settings", [{"scene": "rain"}, {"fps": "fast"}, {"width": None}]
)
def test_test_camera_settings_that_cannot_work_are_refused(settings: dict) -> None:
    with pytest.raises(CameraSettingsError):
        open_source({"connection": "test", "settings": settings}, clock=lambda: 0)
