"""The clock exchange a phone running PhotoFinish Camera makes with its recorder."""

from __future__ import annotations

import socket
import struct

import pytest

from app.recorder import clock_sync
from app.recorder.clock_sync import ClockResponder


def request(t1: int, tag: bytes = b"PFTS", version: int = 1) -> bytes:
    return struct.pack(">4sBq", tag, version, t1)


def test_an_answer_echoes_the_request_with_the_recorder_s_times() -> None:
    answer = clock_sync.answer(request(-42), 1_000, 1_002)
    assert answer is not None
    assert len(answer) == 29
    assert struct.unpack(">4sBqqq", answer) == (b"PFTS", 1, -42, 1_000, 1_002)


def test_anything_but_a_request_gets_no_answer() -> None:
    assert clock_sync.answer(request(1)[:-1], 0, 0) is None
    assert clock_sync.answer(request(1) + b"\x00", 0, 0) is None
    assert clock_sync.answer(request(1, tag=b"PFTX"), 0, 0) is None
    assert clock_sync.answer(request(1, version=2), 0, 0) is None


def test_the_responder_answers_on_its_port_with_its_clock() -> None:
    now = iter(range(5_000, 6_000))
    responder = ClockResponder(0, lambda: next(now), host="127.0.0.1")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as phone:
            phone.settimeout(5)
            phone.sendto(b"not an exchange", ("127.0.0.1", responder.port))
            phone.sendto(request(77), ("127.0.0.1", responder.port))
            data, _ = phone.recvfrom(64)  # the junk was not answered
        tag, version, t1, t2, t3 = struct.unpack(">4sBqqq", data)
        assert (tag, version, t1) == (b"PFTS", 1, 77)
        assert 5_000 <= t2 < t3
    finally:
        responder.close()
    assert not responder._thread.is_alive()


def test_a_port_taken_by_another_program_is_said_and_nothing_left_open() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
        other.bind(("127.0.0.1", 0))
        with pytest.raises(OSError):
            ClockResponder(other.getsockname()[1], lambda: 0, host="127.0.0.1")
