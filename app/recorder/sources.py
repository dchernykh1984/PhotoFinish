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

import collections
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from fractions import Fraction
from typing import Any, Protocol

import av
import numpy as np

from app import cameras
from app.paths import app_path
from app.recorder import frame_time
from app.recorder.segments import RESENT_MS
from app.recorder.testcam import TestCamera

PHONE_APP = "PhotoFinish Camera"  # the encoder its stream's metadata names
UNSTAMPED = "the phone sends its frames without their moments: placed by their arrival"
NOT_IN_STEP = (
    "the phone's moments are out of step with this computer's clock: its frames are "
    "placed by their arrival"
)
OPEN_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 5.0
ADDRESS_FRESH_S = 10.0  # this computer's address, said while waiting, kept this long
LOOK_OVER_US = "500000"  # how long FFmpeg reads a pushed stream before the first frame

type Item = tuple[np.ndarray | av.VideoFrame | av.Packet, int] | None


class CameraSettingsError(ValueError):
    """The camera's settings cannot be recorded; trying again will not help."""


class Source(Protocol):
    fps: float
    clock_note: str  # why a phone's frames are placed by their arrival, or ""
    phone: dict[str, Any]  # a phone's last status and when it came (005), or {}

    @property
    def waiting(self) -> str: ...  # what the recorder says while it yields None

    def frames(self) -> Iterator[Item]: ...


def open_source(
    camera: dict[str, Any],
    clock: Callable[[], int],
    sleep: Callable[[float], None] = time.sleep,
) -> Source:
    """The camera's connection, ready to give frames; ``clock`` gives moments."""
    found = cameras.recording_problems(camera)  # a line or zone drawn: not here
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
        return LiveFile(str(app_path(str(settings["path"]))), clock, sleep)
    if connection == "rtsp":
        options = {"rtsp_transport": settings.get("transport", "tcp")}
        return Stream(settings["url"], options, clock)
    port = settings.get("port", cameras.RTMP_PORT)

    looked: dict[str, Any] = {
        "at": time.monotonic(),
        "address": cameras.this_computer(),
    }

    looking = threading.Lock()  # one lookup at a time: a slow one is not piled on

    def look_again() -> None:
        try:
            looked["address"] = cameras.this_computer()
        finally:
            looking.release()

    def waiting() -> str:
        # Looked up again now and then, on a thread of its own: the computer may join
        # a network meanwhile, and a lookup with none may take a while, during which
        # nothing would listen for the phone.
        stale = time.monotonic() - looked["at"] >= ADDRESS_FRESH_S
        if stale and looking.acquire(blocking=False):
            looked["at"] = time.monotonic()
            threading.Thread(target=look_again, daemon=True).start()
        return f"waiting for {cameras.rtmp_url(settings, looked['address'])}"

    url = f"rtmp://0.0.0.0:{port}/{settings['path']}"
    # FFmpeg looks a stream over before it gives its first frame -- five seconds
    # by default -- and the frames placed by their arrival would be that late.
    options = {"listen": "1", "timeout": "1", "analyzeduration": LOOK_OVER_US}
    return Stream(url, options, clock, listen=True, waiting=waiting)


# A phone's own moment is believed up to this long before its frame is read: the
# look-over, the phone's wait for its clock and the network -- and longer by what it
# says it held the connection's first frame (specs/007). Further back, the phone's
# clock is not in step with this one: its frame is placed by its arrival.
OWN_PAST_MS = 5_000
# A phone's frames placed by their arrival kept by their own moments, to place one sent
# again where it was: what it may send again, at 120 fps.
ARRIVALS_KEPT = RESENT_MS * 120 // 1000
OWN_FUTURE_MS = 250  # a camera stamping a frame as it ends it: the emulator's, by one
SLEW = 0.001  # the share of the time passed by which a clock may be brought nearer
LEAP_MS = 2000  # clocks further apart than this are not drifting: one jumped, or lags


def slewed(skew: float, error: float, elapsed_ms: float) -> float:
    """``skew`` brought nearer ``error`` by SLEW of the time elapsed at most: one
    clock following another slowly as their oscillators drift apart."""
    most = elapsed_ms * SLEW
    return skew + max(-most, min(most, error))


class Anchor:
    """Moments from a camera's timestamps: anchored on the clock at the first one,
    then following the clock slowly -- by a millisecond a second at most, so arrival
    jitter averages out -- as the camera's oscillator and the computer's drift apart
    over a race day."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self.clock = clock
        self._stamp: float | None = None  # the timestamp anchored, ms
        self._moment = 0
        self._last = 0.0
        self._skew = 0.0

    def __call__(self, stamp_ms: float | None, held_ms: int = 0) -> int:
        """The moment of the timestamp ``stamp_ms``; a connection's first, that its
        phone says it held ``held_ms`` (specs/007), anchored that long before now."""
        if stamp_ms is None:
            return self.clock()
        now = self.clock()
        if (
            held_ms
            or self._stamp is None
            or stamp_ms < self._last - 1000
            or stamp_ms > self._last + 5000
        ):
            self._stamp, self._moment, self._skew = stamp_ms, now - held_ms, 0.0
        moment = self._moment + (stamp_ms - self._stamp) + self._skew
        late = now - moment
        if abs(late) <= LEAP_MS:
            self._skew = slewed(self._skew, late, max(stamp_ms - self._last, 0.0))
        self._last = stamp_ms
        return round(self._moment + (stamp_ms - self._stamp) + self._skew)


class UsbCamera:
    """A camera on the computer: avfoundation, dshow or video4linux2 by platform."""

    waiting = ""
    clock_note = ""

    def __init__(self, settings: dict[str, Any], clock: Callable[[], int]) -> None:
        self.fps = float(settings.get("fps", 30))
        self.device, self.format = usb_input(str(settings["device"]))
        self.options = {"framerate": f"{self.fps:g}"}
        if "width" in settings and "height" in settings:
            self.options["video_size"] = f"{settings['width']}x{settings['height']}"
        self.anchor = Anchor(clock)
        self.phone: dict[str, Any] = {}

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


def held_ms(metadata: Mapping[str, str]) -> int:
    """How long PhotoFinish Camera kept a connection's first frame before sending it,
    as its ``onMetaData`` says (specs/007): 0 when it says nothing readable."""
    try:
        return max(round(float(metadata.get("held_ms", 0))), 0)
    except ValueError, OverflowError:
        return 0


class Stream:
    """A network stream, read (RTSP) or received (RTMP, ``listen``); its packets are
    kept as the camera encoded them. A packet that carries its own moment -- PhotoFinish
    Camera's, on the recorder's clock -- is placed by it, others by their arrival, and
    so is one whose moment is in the future or older than OWN_PAST_MS, and what the
    phone says it held the frame, as it is read: a phone whose clock went wrong."""

    def __init__(
        self,
        url: str,
        options: dict[str, str],
        clock: Callable[[], int],
        listen: bool = False,
        waiting: Callable[[], str] = str,
    ) -> None:
        self.url, self.options, self.listen = url, options, listen
        self._waiting = waiting
        self.clock_note = ""
        self.phone: dict[str, Any] = {}
        self.fps = 30.0
        self.anchor = Anchor(clock)
        # A phone's frames placed by their arrival lately, by their own moments: one
        # sent again after a loss is placed where it was (specs/007).
        self._by_arrival: dict[int, int] = {}
        self._arrivals: collections.deque[int] = collections.deque()

    @property
    def waiting(self) -> str:
        return self._waiting()

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
            phone = container.metadata.get("encoder") == PHONE_APP
            place = self._placing(stream, phone, held_ms(container.metadata))
            for packet in container.demux(stream):
                if packet.pts is None or packet.dts is None:
                    continue
                yield packet, place(packet, packet.pts)

    def _placing(
        self,
        stream: av.video.stream.VideoStream,
        phone: bool = False,
        held: int = 0,
    ) -> Callable[[av.Packet, int], int]:
        """Each packet's moment: its own, when the stream's first packet carries one
        the clock can believe as it is read, else its arrival -- for the whole stream.
        The clock relation does not change within a connection, and a frame the Wi-Fi
        held up for seconds keeps its own moment; a phone sends all its frames with
        their moments or none, so the two never mix and the frames keep their order."""
        rate = stream.time_base or Fraction(1, 1000)
        unit = Fraction(rate.numerator, rate.denominator) * 1000
        # Only a phone pushing here stamps its frames: an RTSP camera's are not read.
        stamped = self.listen and stream.codec_context.name == "h264"
        trusted: list[bool] = []  # the first packet's say, for the whole stream
        last: list[int] = []  # the pts and moment of the last frame given

        def place(packet: av.Packet, pts: int) -> int:
            if stamped and getattr(packet, "is_keyframe", True):
                self._hear(packet)
            if trusted and not trusted[0] and not phone:  # another app's: no moments
                return self.anchor(float(pts * unit))
            own = frame_time.moment_ms(memoryview(packet)) if stamped else None
            if not trusted:
                trusted.append(own is not None and self._believed(own, held))
                # Said in the camera list: a phone's frames without moments, or with
                # moments out of step; another camera's never carry them.
                missing = UNSTAMPED if own is None else NOT_IN_STEP
                self.clock_note = missing if phone and not trusted[0] else ""
                if not trusted[0]:  # from when the phone says it took the first
                    return self._arrived(own, self.anchor(float(pts * unit), held))
            if not trusted[0]:
                return self._arrived(own, self.anchor(float(pts * unit)))
            if own is None:  # a trusted stream's frame without it: by its timestamp
                own = last[1] + round(float((pts - last[0]) * unit))
            # A better exchange may move the phone's offset back a little, at its
            # start or in a step: its frames keep their order still.
            moment = max(own, last[1] + 1) if last else own
            last[:] = [pts, moment]
            return moment

        return place

    def _arrived(self, own: int | None, moment: int) -> int:
        """A frame placed by its arrival at ``moment``; a phone's whose own moment
        was so placed lately -- sent again after a loss -- where it was then, so the
        recording lists it once."""
        if own is None:
            return moment
        if own not in self._by_arrival:
            self._by_arrival[own] = moment
            self._arrivals.append(own)
            while len(self._arrivals) > ARRIVALS_KEPT:
                del self._by_arrival[self._arrivals.popleft()]
        return self._by_arrival[own]

    def _hear(self, packet: av.Packet) -> None:
        """The phone's status a keyframe carries, kept with when it came: through a
        reconnect too, so its last readings stay once it stops (specs/005). When on
        two clocks: the recorder's, the frames' own, to say it; this computer's, the
        window's, to tell how old it is -- the recorder's does not follow a clock
        set back."""
        status = frame_time.phone_status(memoryview(packet))
        if status is not None:
            heard = time.time_ns() // 1_000_000
            self.phone = {**status, "at_ms": self.anchor.clock(), "heard_ms": heard}

    def _believed(self, own: int, held: int = 0) -> bool:
        """A phone's own moment as its frame is read: not after it, beyond what a
        camera stamping late gives, and not older than OWN_PAST_MS and the ``held``
        ms the phone says it kept the frame -- else the phone's clock is not in step
        with this one."""
        now = self.anchor.clock()
        return now - OWN_PAST_MS - held <= own <= now + OWN_FUTURE_MS


class LiveFile:
    """A video file played as if a camera were filming it now."""

    waiting = ""
    clock_note = ""

    def __init__(
        self, path: str, clock: Callable[[], int], sleep: Callable[[float], None]
    ) -> None:
        self.path, self.clock, self.sleep = path, clock, sleep
        self.fps = 30.0
        self.phone: dict[str, Any] = {}

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
