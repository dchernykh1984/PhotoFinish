"""A camera's connection opened as a source of frames or packets, each with its moment.

USB cameras and files give decoded frames, which the writer encodes; network streams
give the camera's own packets, which the writer stores as they are. A frame's moment
comes from its own timestamp: the steady clock when the first frame arrived plus the
timestamp's distance from it, anchored again when the timestamp jumps back by more
than a second or forward by more than five (research section 4). A source yields
None while it waits for a camera to call in, so the recorder can say so and still
hear a stop.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from fractions import Fraction
from typing import Any, Protocol

import av
import numpy as np

from app import cameras
from app.recorder.testcam import TestCamera

OPEN_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 5.0

type Item = tuple[np.ndarray | av.VideoFrame | av.Packet, int] | None


class CameraSettingsError(ValueError):
    """The camera's settings cannot be recorded; trying again will not help."""


class Source(Protocol):
    fps: float
    waiting: str  # what the recorder says while the source yields None

    def frames(self) -> Iterator[Item]: ...


def open_source(
    camera: dict[str, Any],
    clock: Callable[[], int],
    sleep: Callable[[float], None] = time.sleep,
) -> Source:
    """The camera's connection, ready to give frames; ``clock`` gives moments."""
    found = cameras.problems(camera)
    if found:
        raise CameraSettingsError("; ".join(found))
    settings = camera.get("settings") or {}
    connection = camera["connection"]
    if connection == "test":
        return TestCamera(
            fps=settings.get("fps", 30),
            width=settings.get("width", 640),
            height=settings.get("height", 360),
            scene=settings.get("scene", "clock"),
            clock=clock,
        )
    if connection == "usb":
        return UsbCamera(settings, clock)
    if connection == "file":
        return LiveFile(str(settings["path"]), clock, sleep)
    if connection == "rtsp":
        options = {"rtsp_transport": settings.get("transport", "tcp")}
        return Stream(settings["url"], options, clock)
    port = settings.get("port", cameras.RTMP_PORT)
    waiting = f"waiting for {cameras.rtmp_url(settings, cameras.this_computer())}"
    url = f"rtmp://0.0.0.0:{port}/{settings['path']}"
    return Stream(
        url, {"listen": "1", "timeout": "1"}, clock, listen=True, waiting=waiting
    )


class Anchor:
    """Moments from a camera's timestamps: anchored on the clock at the first one,
    then following the clock slowly -- by a millisecond a second at most, so arrival
    jitter averages out -- as the camera's oscillator and the computer's drift apart
    over a race day."""

    SLEW = 0.001  # the share of the time passed by which it may be brought nearer
    LEAP_MS = 2000  # further apart than this, the camera is late, not drifting

    def __init__(self, clock: Callable[[], int]) -> None:
        self.clock = clock
        self._stamp: float | None = None  # the timestamp anchored, ms
        self._moment = 0
        self._last = 0.0
        self._skew = 0.0

    def __call__(self, stamp_ms: float | None) -> int:
        if stamp_ms is None:
            return self.clock()
        now = self.clock()
        if (
            self._stamp is None
            or stamp_ms < self._last - 1000
            or stamp_ms > self._last + 5000
        ):
            self._stamp, self._moment, self._skew = stamp_ms, now, 0.0
        moment = self._moment + (stamp_ms - self._stamp) + self._skew
        late = now - moment
        if abs(late) <= self.LEAP_MS:
            most = max(stamp_ms - self._last, 0.0) * self.SLEW
            self._skew += max(-most, min(most, late))
        self._last = stamp_ms
        return round(self._moment + (stamp_ms - self._stamp) + self._skew)


class UsbCamera:
    """A camera on the computer: avfoundation, dshow or video4linux2 by platform."""

    waiting = ""

    def __init__(self, settings: dict[str, Any], clock: Callable[[], int]) -> None:
        self.fps = float(settings.get("fps", 30))
        self.device, self.format = usb_input(str(settings["device"]))
        self.options = {"framerate": f"{self.fps:g}"}
        if "width" in settings and "height" in settings:
            self.options["video_size"] = f"{settings['width']}x{settings['height']}"
        self.anchor = Anchor(clock)

    def frames(self) -> Iterator[Item]:
        with av.open(
            self.device,
            format=self.format,
            options=self.options,
            timeout=(OPEN_TIMEOUT_S, READ_TIMEOUT_S),
        ) as container:
            for frame in container.decode(video=0):
                stamp = None if frame.time is None else frame.time * 1000
                yield frame, self.anchor(stamp)


def usb_input(device: str) -> tuple[str, str]:
    """The device as FFmpeg's capture input of this platform names it."""
    if sys.platform == "darwin":
        return f"{device}:none", "avfoundation"
    if sys.platform == "win32":
        return f"video={device}", "dshow"
    return device, "video4linux2"


class Stream:
    """A network stream, read (RTSP) or received (RTMP, ``listen``); its packets are
    kept as the camera encoded them."""

    def __init__(
        self,
        url: str,
        options: dict[str, str],
        clock: Callable[[], int],
        listen: bool = False,
        waiting: str = "",
    ) -> None:
        self.url, self.options, self.listen, self.waiting = (
            url,
            options,
            listen,
            waiting,
        )
        self.fps = 30.0
        self.anchor = Anchor(clock)

    def frames(self) -> Iterator[Item]:
        # A listening open waits a second for the camera app at a time; a stream
        # that stops sending fails after the read timeout and is opened again.
        timeout = (None if self.listen else OPEN_TIMEOUT_S, READ_TIMEOUT_S)
        while True:
            try:
                container = av.open(self.url, options=self.options, timeout=timeout)
                break
            except TimeoutError:
                if not self.listen:
                    raise
                yield None
        with container:
            stream = container.streams.video[0]
            self.fps = float(stream.average_rate or stream.guessed_rate or 30)
            rate = stream.time_base or Fraction(1, 1000)
            unit = Fraction(rate.numerator, rate.denominator) * 1000
            for packet in container.demux(stream):
                if packet.pts is None or packet.dts is None:
                    continue
                yield packet, self.anchor(float(packet.pts * unit))


class LiveFile:
    """A video file played as if a camera were filming it now."""

    waiting = ""

    def __init__(
        self, path: str, clock: Callable[[], int], sleep: Callable[[float], None]
    ) -> None:
        self.path, self.clock, self.sleep = path, clock, sleep
        self.fps = 30.0

    def frames(self) -> Iterator[Item]:
        with av.open(self.path) as container:
            stream = container.streams.video[0]
            self.fps = float(stream.average_rate or stream.guessed_rate or 30)
            start, first = self.clock(), None
            for frame in container.decode(stream):
                if frame.time is None:
                    continue
                first = frame.time if first is None else first
                due = start + round((frame.time - first) * 1000)
                wait = due - self.clock()
                if wait > 0:
                    self.sleep(wait / 1000)
                yield frame, due
