"""Camera connections, presets and the settings each needs."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from app import cameras
from app.cameras import PRESETS, problems


@pytest.fixture(autouse=True)
def capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """A computer that captures USB cameras, whatever this one does."""
    monkeypatch.setattr(cameras, "usb_capture", lambda: "avfoundation")


def test_the_presets_fill_in_cameras_that_can_record_and_say_untested() -> None:
    assert [p.id for p in PRESETS] == [
        "sjcam-hd1080p-usb",
        "sjcam-hd1080p-wifi",
        "sjcam-sj10pro-rtmp",
    ]
    for preset in PRESETS:
        assert preset.label.endswith(" (untested)")
        assert (
            problems({"connection": preset.connection, "settings": preset.settings})
            == []
        )
    tested = cameras.Preset("x", "Tried", "test", tested=True)
    assert tested.label == "Tried"


GOOD: list[dict[str, Any]] = [
    {"connection": "usb", "settings": {"device": "PC Camera"}},
    {"connection": "usb", "settings": {"device": "0", "width": 1280, "height": 720}},
    {
        "connection": "rtsp",
        "settings": {"url": "rtsp://10.0.0.2/x", "transport": "udp"},
    },
    {"connection": "rtmp", "settings": {"path": "live/cam"}},
    {"connection": "test", "settings": {}},
    {"connection": "test", "settings": {"fps": 59.94, "scene": "bar"}},
    {"connection": "file", "settings": {"path": "race.mp4"}, "offset_ms": -40},
    {
        "connection": "test",
        "finish_line": [[0.5, 0], [0.5, 1]],
        "record": True,
    },
]


@pytest.mark.parametrize("camera", GOOD)
def test_cameras_that_can_record(camera: dict[str, Any]) -> None:
    assert problems(camera) == []


BAD: list[tuple[dict[str, Any], str]] = [
    ({"connection": "pigeon"}, "unknown connection"),
    ({"connection": "test", "settings": [1]}, "table"),
    ({"connection": "usb", "settings": {"device": " "}}, "name is missing"),
    ({"connection": "usb", "settings": {"device": "a", "width": 1279}}, "even"),
    ({"connection": "usb", "settings": {"device": "a", "fps": 0}}, "frame rate"),
    ({"connection": "usb", "settings": {"device": "a", "fps": True}}, "frame rate"),
    ({"connection": "rtsp", "settings": {"url": "http://x"}}, "rtsp://"),
    ({"connection": "rtsp", "settings": {"url": "rtsp://x", "transport": "x"}}, "tcp"),
    ({"connection": "rtmp", "settings": {"port": 0, "path": "a"}}, "port"),
    ({"connection": "rtmp", "settings": {"path": "/live/x"}}, "like live/camera"),
    ({"connection": "rtmp", "settings": {}}, "like live/camera"),
    ({"connection": "test", "settings": {"width": 320, "height": 240}}, "352"),
    ({"connection": "test", "settings": {"scene": "rain"}}, "scene"),
    ({"connection": "file", "settings": {}}, "file is missing"),
    ({"connection": "test", "finish_line": [[0, 0], [0, 0]]}, "finish line"),
    ({"connection": "test", "finish_line": [[0, 0], [2, 1]]}, "finish line"),
    ({"connection": "test", "finish_line": [[0, "x"], [1, 1]]}, "finish line"),
    ({"connection": "test", "finish_line": [0, 1]}, "finish line"),
    ({"connection": "test", "finish_line": "centre"}, "finish line"),
    ({"connection": "test", "offset_ms": 1.5}, "whole milliseconds"),
]


@pytest.mark.parametrize(("camera", "said"), BAD)
def test_cameras_that_cannot_record_say_why(camera: dict[str, Any], said: str) -> None:
    found = problems(camera)
    assert len(found) == 1
    assert said in found[0]


def test_a_computer_without_usb_capture_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cameras, "usb_capture", lambda: None)
    assert problems({"connection": "usb", "settings": {"device": "0"}}) == [
        "this build cannot capture USB cameras on this computer: "
        "use the camera's stream or a file"
    ]


def test_the_rtmp_address_to_type_in_the_camera_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        cameras.rtmp_url({"path": "live/x"}, "10.0.0.5")
        == "rtmp://10.0.0.5:1935/live/x"
    )
    assert cameras.this_computer().count(".") == 3

    class Unrouted(socket.socket):
        def connect(self, address: Any) -> None:
            raise OSError("no route")

    monkeypatch.setattr(socket, "socket", Unrouted)
    assert cameras.this_computer() == "127.0.0.1"
