"""What PhotoFinish Camera writes into a frame: H.264 SEI messages -- or H.265's,
the same messages in prefix SEI units (specs/010-hevc).

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
HEVC_PREFIX_SEI = 39
USER_DATA_UNREGISTERED = 5
_PICTURE = range(1, 6)  # coded slices: the SEI, when there is one, came before
_HEVC_PICTURE = range(32)  # H.265's VCL units


def moment_ms(packet: bytes | memoryview, hevc: bool = False) -> int | None:
    """The moment written into an H.264 packet -- an H.265 one with ``hevc`` -- as
    RTMP carries it, each unit after its length in four bytes, in milliseconds;
    None when it has none. A memoryview is read without a copy."""
    moment = _found(packet, MARK, hevc, least=8)
    if moment is None:
        return None
    return (int.from_bytes(moment[:8], signed=True) + 500) // 1000


def phone_status(
    packet: bytes | memoryview, hevc: bool = False
) -> dict[str, str] | None:
    """The phone's status written into a packet, its readings by key; None when it
    carries none. A reading's value is kept as written: what it means is the
    window's to say."""
    line = _found(packet, STATUS, hevc)
    if line is None:
        return None
    pairs = line.decode("ascii", "replace").split(";")
    return dict(pair.split("=", 1) for pair in pairs if "=" in pair)


def _found(
    packet: bytes | memoryview, mark: bytes, hevc: bool, least: int = 0
) -> bytes | None:
    """What follows ``mark`` in the first SEI message of that kind before the
    packet's picture, of ``least`` bytes at least -- one cut shorter passed over:
    H.264's units have a byte of header, H.265's two."""
    for start, end in _units(packet):
        if hevc:
            kind, header, picture, sei = (
                (packet[start] >> 1) & 0x3F,
                2,
                _HEVC_PICTURE,
                HEVC_PREFIX_SEI,
            )
        else:
            kind, header, picture, sei = packet[start] & 0x1F, 1, _PICTURE, NAL_SEI
        if kind in picture:
            return None
        if kind == sei:
            found = _message(_unescape(bytes(packet[start + header : end])), mark)
            if found is not None and len(found) >= least:
                return found
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
