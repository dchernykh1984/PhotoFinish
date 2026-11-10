"""The clock exchange that puts PhotoFinish Camera's frames on the recorder's clock.

The phone asks over UDP, on the port number its RTMP stream comes in on, what the
time is here; the recorder answers with its own clock, in microseconds, the clock
its frames' moments are kept on. From the exchanges the phone works out how far
its camera's clock is from this one and writes each frame's moment on this clock
into the frame itself (specs/003-phone-camera-app/contracts/phone-stream.md).
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import threading
from collections.abc import Callable

TAG = b"PFTS"
VERSION = 1
REQUEST = struct.Struct(">4sBq")  # tag, version, t1: sent on the phone's clock
ANSWER = struct.Struct(">4sBqqq")  # tag, version, t1, t2 received, t3 sent here
_RETRY_S = 0.1


def answer(request: bytes, t2: int, t3: int) -> bytes | None:
    """The answer to ``request``, received at ``t2`` and sent at ``t3``; None when
    it is not a request."""
    if len(request) != REQUEST.size:
        return None
    tag, version, t1 = REQUEST.unpack(request)
    if tag != TAG or version != VERSION:
        return None
    return ANSWER.pack(TAG, VERSION, t1, t2, t3)


def may_ask(host: str) -> bool:
    """A sender on this network -- a private, link-local or loopback address -- and
    no stranger from beyond it: the answer is longer than the request."""
    return ipaddress.ip_address(host).is_private


class ClockResponder:
    """Answers the exchange on UDP ``port`` with ``micros``, on a thread of its own,
    until closed."""

    def __init__(self, port: int, micros: Callable[[], int], host: str = "") -> None:
        self.micros = micros
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind((host, port))  # every interface: the phone is on Wi-Fi
        except OSError:
            self.socket.close()
            raise
        self.socket.settimeout(0.5)
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._serve, name="clock-responder", daemon=True
        )
        self._thread.start()

    @property
    def port(self) -> int:
        return int(self.socket.getsockname()[1])

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                request, sender = self.socket.recvfrom(64)
                t2 = self.micros()
                reply = answer(request, t2, self.micros())
                if reply is not None and may_ask(sender[0]):
                    self.socket.sendto(reply, sender)
            except TimeoutError:
                continue
            except OSError:
                # Closed; or Windows saying an earlier answer found no one, or a
                # network gone: tried again after a pause, not in a busy loop.
                if self._closed.wait(_RETRY_S):
                    return

    def close(self) -> None:
        self._closed.set()
        self.socket.close()
        self._thread.join(timeout=2)
