"""A frame's moment read from the SEI PhotoFinish Camera puts in front of it."""

from __future__ import annotations

from app.recorder import frame_time

MOMENT_US = 1_794_329_044_562_500  # 2026-11-10, half a millisecond in
IDR = b"\x65\x88\x84\x00\x33"
SLICE = b"\x41\x9a\x00\x00\x03"


def escape(rbsp: bytes) -> bytes:
    """H.264's emulation prevention: a 03 after two zeros, before a byte up to 3."""
    out = bytearray()
    zeros = 0
    for byte in rbsp:
        if zeros >= 2 and byte <= 3:
            out.append(3)
            zeros = 0
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)


def sei(moment_us: int, uuid: bytes = frame_time.UUID) -> bytes:
    """The SEI NAL unit the app writes for a frame taken at ``moment_us``."""
    payload = uuid + b"PFT1" + moment_us.to_bytes(8, signed=True)
    return b"\x06" + escape(bytes([5, len(payload)]) + payload + b"\x80")


def avcc(*units: bytes) -> bytes:
    """The units as RTMP carries them: each after its length in four bytes."""
    return b"".join(len(unit).to_bytes(4) + unit for unit in units)


def test_the_moment_is_read_from_a_packet_as_rtmp_brings_it() -> None:
    assert frame_time.moment_ms(avcc(sei(MOMENT_US), IDR)) == 1_794_329_044_563
    assert frame_time.moment_ms(avcc(sei(MOMENT_US - 1), SLICE)) == 1_794_329_044_562


def test_a_moment_with_zero_bytes_comes_through_their_escaping() -> None:
    moment_us = 0x0000_0100_0002_0000  # runs of zeros: escaped in the SEI
    unit = sei(moment_us)
    assert b"\x00\x00\x03\x01" in unit
    assert frame_time.moment_ms(avcc(unit, IDR)) == (moment_us + 500) // 1000


def test_another_sei_before_it_is_passed_over() -> None:
    long = bytes([5, 0xFF, 0x2D]) + bytes(300) + b"\x80"  # size 255 + 45
    other = b"\x06" + escape(long)
    assert avcc(other).startswith(b"\x00\x00\x01")  # a length like a start code
    assert frame_time.moment_ms(avcc(other, sei(MOMENT_US), IDR)) is not None
    foreign = sei(MOMENT_US, uuid=bytes(range(16)))  # x264's options, say
    assert frame_time.moment_ms(avcc(foreign, IDR)) is None


def test_a_packet_without_the_moment_has_none() -> None:
    assert frame_time.moment_ms(avcc(IDR)) is None
    assert (
        frame_time.moment_ms(avcc(IDR, sei(MOMENT_US))) is None
    )  # after: not looked for
    assert frame_time.moment_ms(b"") is None


def test_a_broken_packet_has_no_moment_and_raises_nothing() -> None:
    whole = avcc(sei(MOMENT_US), IDR)
    for cut in range(len(whole)):
        frame_time.moment_ms(whole[:cut])  # no exception, whatever is left
    assert frame_time.moment_ms(b"\x00\x00\x00\xff\x06\x05") is None
    short = b"\x06" + bytes([5, 28]) + frame_time.MARK + b"\x01\x02\x80"
    assert frame_time.moment_ms(avcc(short, IDR)) is None
