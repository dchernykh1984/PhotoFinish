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


def test_a_phone_s_other_lenses_take_the_next_ids_and_free_ports() -> None:
    first = {"port": 1936, "path": "live/finish"}
    made = cameras.lens_cameras(
        ["main", "telephoto", "front"], ["cam2", "cam3", "cam5"], first, {1935, 1938}
    )
    assert made == [
        ("main", "cam2", first),
        ("telephoto", "cam3", {"port": 1937, "path": "live/cam3"}),
        ("front", "cam5", {"port": 1939, "path": "live/cam5"}),  # 1938: another phone's
    ]
    assert len(cameras.lens_cameras(["main", "front"], ["cam2"], first, set())) == 1


def test_the_pairing_code_is_the_address_alone_only_for_the_main_lens_alone() -> None:
    main, tele = "rtmp://10.0.0.5:1935/live/cam1", "rtmp://10.0.0.5:1936/live/cam2"
    assert cameras.pairing_text([("main", main)]) == main  # any streaming app reads it
    assert cameras.pairing_text([("telephoto", tele)]) == f"telephoto {tele}"
    assert cameras.pairing_text([("main", main), ("telephoto", tele)]) == (
        f"main {main}\ntelephoto {tele}"
    )


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
    own: list[str] = []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, 0, 0, "", (ip, 0)) for ip in own],
    )
    assert cameras.this_computer() == "127.0.0.1"  # no network at all
    own[:] = ["127.0.1.1", "10.42.0.1"]  # an offline network with no gateway
    assert cameras.this_computer() == "10.42.0.1"
    # A self-assigned address and a virtual machine's adapter are not the Wi-Fi.
    own[:] = ["169.254.3.4", "172.27.0.1", "192.168.1.20"]
    assert cameras.this_computer() == "192.168.1.20"
    own[:] = ["169.254.3.4", "172.20.10.2"]  # an iPhone's hotspot
    assert cameras.this_computer() == "172.20.10.2"
    own[:] = ["198.18.0.1"]  # a proxy's made-up address: no network for a phone
    assert cameras.this_computer() == "127.0.0.1"
    own[:] = ["100.101.102.103"]  # a carrier's or Tailscale's, as the exchange takes
    assert cameras.this_computer() == "100.101.102.103"


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
        "port 1935 is also cam2's: each phone needs its own"
    )
    assert port_clash(second, session_cameras) == (
        "port 1935 is also Line's: each phone needs its own"
    )
    assert port_clash(third, session_cameras) is None
    assert port_clash(test, session_cameras) is None
