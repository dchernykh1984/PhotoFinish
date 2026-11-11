"""What PhotoFinish Camera writes into a frame: H.264 SEI messages.

A user_data_unregistered message (payload type 5) with PhotoFinish's UUID, then
"PFT1" and the moment the frame was taken, in microseconds on the recorder's clock,
as a signed 64-bit big-endian number (contracts/phone-stream.md). The SEI comes
before the frame's picture; a packet without one is placed by its arrival. A
keyframe also carries "PFS1" and the phone's status, ``key=value`` pairs separated
by ``;`` (specs/005-phone-status).
"""

from __future__ import annotations

from collections.abc import Iterator

UUID = bytes.fromhex("e1a46ceab5ff4c7db4454c7dbd7ea281")
MARK = UUID + b"PFT1"
STATUS = UUID + b"PFS1"
NAL_SEI = 6
USER_DATA_UNREGISTERED = 5
_PICTURE = range(1, 6)  # coded slices: the SEI, when there is one, came before


def moment_ms(packet: bytes | memoryview) -> int | None:
    """The moment written into an H.264 packet as RTMP carries it -- each unit after
    its length in four bytes -- in milliseconds; None when it has none. A memoryview
    is read without a copy."""
    for start, end in _units(packet):
        kind = packet[start] & 0x1F
        if kind in _PICTURE:
            return None
        if kind == NAL_SEI:
            moment = _message(_unescape(bytes(packet[start + 1 : end])), MARK)
            if moment is not None and len(moment) >= 8:
                return (int.from_bytes(moment[:8], signed=True) + 500) // 1000
    return None


def phone_status(packet: bytes | memoryview) -> dict[str, str] | None:
    """The phone's status written into a packet, its readings by key; None when it
    carries none. A reading's value is kept as written: what it means is the
    window's to say."""
    for start, end in _units(packet):
        kind = packet[start] & 0x1F
        if kind in _PICTURE:
            return None
        if kind == NAL_SEI:
            line = _message(_unescape(bytes(packet[start + 1 : end])), STATUS)
            if line is not None:
                pairs = line.decode("ascii", "replace").split(";")
                return dict(pair.split("=", 1) for pair in pairs if "=" in pair)
    return None


def _units(data: bytes | memoryview) -> Iterator[tuple[int, int]]:
    """Where each length-prefixed NAL unit starts and ends."""
    pos = 0
    while pos + 4 < len(data):
        size = int.from_bytes(data[pos : pos + 4])
        pos += 4
        if size == 0 or pos + size > len(data):
            return
        yield pos, pos + size
        pos += size


def _message(rbsp: bytes, mark: bytes) -> bytes | None:
    """What follows ``mark`` in the SEI's message that begins with it; None when no
    message is PhotoFinish's of that kind."""
    end = len(rbsp.rstrip(b"\x00")) - 1  # the last byte holds the trailing bits
    pos = 0
    while pos < end:
        kind, pos = _number(rbsp, pos)
        size, pos = _number(rbsp, pos)
        payload = rbsp[pos : pos + size]
        if kind == USER_DATA_UNREGISTERED and payload[: len(mark)] == mark:
            return payload[len(mark) :]
        pos += size
    return None


def _number(data: bytes, pos: int) -> tuple[int, int]:
    """An SEI payload type or size: 255 for each 0xFF byte, then the last byte."""
    value = 0
    while pos < len(data) and data[pos] == 0xFF:
        value += 255
        pos += 1
    if pos < len(data):
        value += data[pos]
    return value, pos + 1


def _unescape(data: bytes) -> bytes:
    """The bytes without H.264's emulation prevention: 00 00 03 is 00 00."""
    if b"\x00\x00\x03" not in data:
        return data
    out = bytearray()
    zeros = 0
    for byte in data:
        if zeros >= 2 and byte == 3:
            zeros = 0
            continue
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)
