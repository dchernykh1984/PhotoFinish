"""Camera connections and the settings each needs."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from app import cameras
from app.cameras import port_clash, ports_taken, problems


@pytest.fixture(autouse=True)
def capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """A computer that captures USB cameras, whatever this one does."""
    monkeypatch.setattr(cameras, "usb_capture", lambda: "avfoundation")


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
    ({"connection": "usb", "settings": {"device": "a", "width": 1279}}, "both"),
    (
        {
            "connection": "usb",
            "settings": {"device": "a", "width": 1279, "height": 720},
        },
        "even",
    ),
    ({"connection": "test", "settings": {"height": 720}}, "both"),
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


def test_each_phone_listens_on_a_port_of_its_own() -> None:
    session_cameras: list[dict[str, Any]] = [
        {"connection": "rtmp", "settings": {"path": "live/a"}},
        {"connection": "rtmp", "settings": {"port": 1936, "path": "live/b"}},
        {"connection": "test", "settings": {"port": 1937}},
        {"connection": "rtmp"},
    ]
    assert ports_taken(session_cameras) == {1935, 1936}
    assert ports_taken([]) == set()


def test_a_phone_with_settings_not_a_phones_takes_no_port() -> None:
    broken: list[dict[str, Any]] = [
        {"connection": "rtmp", "settings": {"port": None}},
        {"connection": "rtmp", "settings": {"port": "abc"}},
        {"connection": "rtmp", "settings": {"port": True}},
        {"connection": "rtmp", "settings": [1935]},
        {"connection": "rtmp", "settings": None},
    ]
    assert ports_taken(broken) == set()


def test_phones_sharing_a_port_both_say_so() -> None:
    first = {"id": "cam1", "name": "Line", "connection": "rtmp", "settings": {}}
    second = {"id": "cam2", "connection": "rtmp", "settings": {"port": 1935}}
    third = {"id": "cam3", "connection": "rtmp", "settings": {"port": 1936}}
    test = {"id": "cam4", "connection": "test", "settings": {}}
    session_cameras = [first, second, third, test]
    assert port_clash(first, session_cameras) == (
        "port 1935 is shared with cam2: remove one, add it again"
    )
    assert port_clash(second, session_cameras) == (
        "port 1935 is shared with Line: remove one, add it again"
    )
    assert port_clash(third, session_cameras) is None
    assert port_clash(test, session_cameras) is None
