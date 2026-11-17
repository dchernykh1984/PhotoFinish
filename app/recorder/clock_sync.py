"""The clock exchange that puts PhotoFinish Camera's frames on the recorder's clock.

The phone asks over UDP, on the port number its RTMP stream comes in on, what the
time is here; the recorder answers with its own clock, in microseconds, the clock
its frames' moments are kept on. From the exchanges the phone works out how far
its camera's clock is from this one and writes each frame's moment on this clock
into the frame itself (specs/003-phone-camera-app/contracts/phone-stream.md).
"""

from __future__ import annotations

import contextlib
import queue
import socket
import struct
import threading
import time
from collections.abc import Callable
from typing import Any

TAG = b"PFTS"
VERSION = 1
REQUEST = struct.Struct(">4sBq")  # tag, version, t1: sent on the phone's clock
ANSWER = struct.Struct(">4sBqqq")  # tag, version, t1, t2 received, t3 sent here
_RETRY_S = 0.1
# The answer is longer than the request: rationed, no stranger can make this computer
# send much elsewhere -- 1.5 kB a second at most -- while hundreds of phones fit.
ANSWERS_PER_S = 50
DATAGRAM_BYTES = 2048  # a log message of the phone's, 1,200 bytes at most, whole
OTHERS_WAITING = 64  # log messages waiting for their thread; past them, sent again


def answer(request: bytes, t2: int, t3: int) -> bytes | None:
    """The answer to ``request``, received at ``t2`` and sent at ``t3``; None when
    it is not a request."""
    if len(request) != REQUEST.size:
        return None
    tag, version, t1 = REQUEST.unpack(request)
    if tag != TAG or version != VERSION:
        return None
    return ANSWER.pack(TAG, VERSION, t1, t2, t3)


class ClockResponder:
    """Answers the exchange on UDP ``port`` with ``micros``, on a thread of its own,
    until closed: any sender, as a venue's Wi-Fi may hand out public addresses, but
    ANSWERS_PER_S at most. A datagram that is no exchange goes to ``others``, whose
    answer is sent back: the phone's log (specs/008-phone-log), on a thread of its own,
    so that its file costs the exchange no moment."""

    def __init__(
        self,
        port: int,
        micros: Callable[[], int],
        host: str = "",
        monotonic: Callable[[], float] = time.monotonic,
        others: Callable[[bytes], bytes | None] | None = None,
    ) -> None:
        self.micros, self.monotonic, self.others = micros, monotonic, others
        # Each kind's second and the answers of it in that second, from both threads.
        self._spent: dict[str, tuple[float, int]] = {}
        self._rationed = threading.Lock()
        self._waiting: queue.Queue[tuple[bytes, Any]] = queue.Queue(OTHERS_WAITING)
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
        self._worker = None
        if others is not None:
            self._worker = threading.Thread(
                target=self._work, args=(others,), name="phone-log", daemon=True
            )
            self._worker.start()

    @property
    def port(self) -> int:
        return int(self.socket.getsockname()[1])

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                request, sender = self.socket.recvfrom(DATAGRAM_BYTES)
                t2 = self.micros()
                reply = answer(request, t2, self.micros())
                if reply is None and self.others is not None:
                    with contextlib.suppress(queue.Full):  # the phone sends it again
                        self._waiting.put_nowait((request, sender))
                elif reply is not None and self.may_answer():
                    self.socket.sendto(reply, sender)
            except TimeoutError:
                continue
            except ConnectionResetError:
                # Windows: an earlier answer -- the phone's log's too -- found no one.
                # One reset for each answer sent: no pause, the exchange answered on.
                continue
            except OSError:
                # Closed, or a network gone: tried again after a pause, not in a busy
                # loop.
                if self._closed.wait(_RETRY_S):
                    return

    def _work(self, others: Callable[[bytes], bytes | None]) -> None:
        """The datagrams that are no exchange, to ``others``, its answers sent back;
        whatever it raises costs that datagram alone, never the clock exchange the
        frames' moments come from."""
        while not self._closed.is_set():
            try:
                datagram, sender = self._waiting.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                reply = others(datagram)
            except Exception:  # the log costs the video nothing (008, FR-006)
                reply = None
            if reply is not None and self.may_answer("log"):
                with contextlib.suppress(OSError):  # closed meanwhile, or no route
                    self.socket.sendto(reply, sender)

    def may_answer(self, of: str = "clock") -> bool:
        """Another answer this second: ANSWERS_PER_S at most of each kind -- answers to
        the log never spend the clock exchange's, which the frames' moments need."""
        with self._rationed:
            now = self.monotonic()
            second, answered = self._spent.get(of, (0.0, 0))
            if now - second >= 1:
                second, answered = now, 0
            self._spent[of] = (second, answered + 1)
            return answered + 1 <= ANSWERS_PER_S

    def close(self) -> None:
        self._closed.set()
        self.socket.close()
        self._thread.join(timeout=2)
        if self._worker is not None:
            self._worker.join(timeout=2)
