"""A camera's connection opened as a source of frames, each with its moment."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Protocol

import av
import numpy as np

from app.recorder.testcam import TestCamera


class CameraSettingsError(ValueError):
    """The camera's settings cannot be recorded; trying again will not help."""


class Source(Protocol):
    fps: float

    def frames(self) -> Iterator[tuple[np.ndarray | av.VideoFrame, int]]: ...


def open_source(camera: dict[str, Any], clock: Callable[[], int]) -> Source:
    """The camera's connection, opened; ``clock`` gives each frame its moment."""
    settings = camera.get("settings") or {}
    connection = camera.get("connection")
    try:
        if connection == "test":
            return TestCamera(
                fps=float(settings.get("fps", 30)),
                width=int(settings.get("width", 640)),
                height=int(settings.get("height", 360)),
                scene=str(settings.get("scene", "clock")),
                clock=clock,
            )
    except (TypeError, ValueError) as error:
        raise CameraSettingsError(str(error)) from error
    raise CameraSettingsError(f"unknown connection {connection!r}")
