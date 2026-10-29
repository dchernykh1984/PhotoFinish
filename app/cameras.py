"""Camera connections, the maintainer's presets, and what a camera's settings must be.

A camera is a dict in the session (data-model.md): ``connection`` is one of
``CONNECTIONS`` and ``settings`` holds what that connection needs. ``problems``
says what keeps one from recording; the window shows it and the recorder refuses
such a camera.
"""

from __future__ import annotations

import re
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import av

from app import analysis
from app.interpolation import points
from app.recorder.testcam import SCENES

CONNECTIONS = ("usb", "rtsp", "rtmp", "test", "file")
RTMP_PORT = 1935
_RTMP_PATH = re.compile(r"[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*")


@dataclass(frozen=True)
class Preset:
    """A camera the maintainer owns, as a connection filled in. ``tested`` once it
    has recorded with that very camera."""

    id: str
    name: str
    connection: str
    settings: dict[str, Any] = field(default_factory=dict)
    tested: bool = False

    @property
    def label(self) -> str:
        return self.name if self.tested else f"{self.name} (untested)"


PRESETS = (
    Preset(
        "sjcam-hd1080p-usb",
        "SJCAM HD1080P over USB",
        "usb",
        {"device": "PC Camera", "width": 1280, "height": 720, "fps": 30},
    ),
    Preset(
        "sjcam-hd1080p-wifi",
        "SJCAM HD1080P over its Wi-Fi",
        "rtsp",
        {"url": "rtsp://192.168.1.254/sjcam.mov"},
    ),
    Preset(
        "sjcam-sj10pro-rtmp",
        "SJCAM SJ10 Pro over RTMP",
        "rtmp",
        {"port": RTMP_PORT, "path": "live/sj10pro"},
    ),
)


def recording_problems(camera: dict[str, Any]) -> list[str]:
    """What keeps the camera from recording; empty when nothing does."""
    connection = camera.get("connection")
    if connection not in CONNECTIONS:
        return [f"unknown connection {connection!r}"]
    settings = camera.get("settings") or {}
    if not isinstance(settings, dict):
        return ["settings must be a table"]
    return _CHECKS[connection](settings)


def problems(camera: dict[str, Any]) -> list[str]:
    """What is wrong in the camera's settings: what keeps it from recording, and the
    finish line, offset and zone the window uses, which never stop a recording."""
    found = recording_problems(camera)
    line = camera.get("finish_line")
    if line is not None and points(line) is None:
        found.append("the finish line must be two different points within the picture")
    if not isinstance(camera.get("offset_ms", 0), int):
        found.append("the offset must be whole milliseconds")
    if camera.get("zone") is not None and not analysis.valid_zone(camera["zone"]):
        found.append("the zone must be two corners of a part of the picture")
    return found


def rtmp_url(settings: dict[str, Any], host: str) -> str:
    """The address the camera app pushes to."""
    return f"rtmp://{host}:{settings.get('port', RTMP_PORT)}/{settings['path']}"


def this_computer() -> str:
    """This computer's address on the local network, for a camera app to push to."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # picks the route; no packet is sent
            return str(probe.getsockname()[0])
        except OSError:
            return "127.0.0.1"


def usb_capture() -> str | None:
    """FFmpeg's camera input on this computer, when the bundled FFmpeg has it. The
    Linux wheels of PyAV come without video4linux2."""
    name = {"darwin": "avfoundation", "win32": "dshow"}.get(
        sys.platform, "video4linux2"
    )
    return name if name in av.formats_available else None


def _usb(settings: dict[str, Any]) -> list[str]:
    found = (
        [] if _text(settings.get("device")) else ["the USB camera's name is missing"]
    )
    if usb_capture() is None:
        found.append(
            "this build cannot capture USB cameras on this computer: "
            "use the camera's stream or a file"
        )
    return found + _size(settings, 2) + _fps(settings)


def _rtsp(settings: dict[str, Any]) -> list[str]:
    url = settings.get("url")
    found = []
    if not (isinstance(url, str) and url.startswith(("rtsp://", "rtsps://"))):
        found.append("the stream's address must start with rtsp://")
    if settings.get("transport", "tcp") not in ("tcp", "udp"):
        found.append("the transport must be tcp or udp")
    return found


def _rtmp(settings: dict[str, Any]) -> list[str]:
    port = settings.get("port", RTMP_PORT)
    found = []
    if not (isinstance(port, int) and 0 < port < 65536):
        found.append("the port must be a number from 1 to 65535")
    path = settings.get("path")
    if not (isinstance(path, str) and _RTMP_PATH.fullmatch(path)):
        found.append("the stream's path must be like live/camera")
    return found


def _test(settings: dict[str, Any]) -> list[str]:
    found = _size(settings, 352) + _fps(settings)
    if settings.get("scene", "clock") not in SCENES:
        found.append(f"the scene must be one of {', '.join(SCENES)}")
    return found


def _file(settings: dict[str, Any]) -> list[str]:
    return [] if _text(settings.get("path")) else ["the video file is missing"]


_CHECKS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "usb": _usb,
    "rtsp": _rtsp,
    "rtmp": _rtmp,
    "test": _test,
    "file": _file,
}


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _size(settings: dict[str, Any], least_width: int) -> list[str]:
    if ("width" in settings) != ("height" in settings):
        return ["the picture size needs its width and its height both"]
    if "width" not in settings and least_width < 352:
        return []
    width, height = settings.get("width", 640), settings.get("height", 360)
    if not all(isinstance(v, int) and v >= 64 and v % 2 == 0 for v in (width, height)):
        return ["the picture size must be even numbers of pixels, 64 or more"]
    if width < least_width:
        return [f"the picture must be at least {least_width} pixels wide"]
    return []


def _fps(settings: dict[str, Any]) -> list[str]:
    fps = settings.get("fps", 30)
    ok = isinstance(fps, int | float) and not isinstance(fps, bool) and 1 <= fps <= 240
    return [] if ok else ["the frame rate must be from 1 to 240"]
