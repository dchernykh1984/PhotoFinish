"""Crossing lines and times, read and written the way the chronometers do."""

from __future__ import annotations

import time

import pytest

from app import lines


def test_a_time_reads_as_the_chronometers_write_it() -> None:
    assert lines.parse_time("20389 11:35:29.615") == 20389 * 86_400_000 + 41_729_615
    assert lines.parse_time("1 2:3:4") == 86_400_000 + 7_384_000
    for bad in ("1 24:0:0", "1 2:60:0", "1 2:3:4.5", "x", "", "1 02:03"):
        assert lines.parse_time(bad) is None, bad


def test_a_time_is_written_without_padding_and_with_three_digit_millis() -> None:
    assert lines.scale_time(86_400_000 + 7_384_005) == "1 2:3:4.005"
    assert lines.parse_time(lines.scale_time(1_761_716_129_587)) == 1_761_716_129_587


def test_a_line_gives_its_number_time_and_action() -> None:
    c = lines.parse_line("15#20389 11:35:29.615#nextLap#")
    assert (c.number, c.action) == ("15", "nextLap")
    assert c.ms == lines.parse_time("20389 11:35:29.615")
    assert lines.parse_line("15##").ms is None
    assert lines.parse_line("15").ms is None
    finish = lines.format_line("15", c.ms or 0, "finish")
    assert finish == "15#20389 11:35:29.615#finish#"


@pytest.fixture
def zone(monkeypatch):
    """UTC+5 standard time, daylight saving set by the test."""
    monkeypatch.setattr(time, "timezone", -5 * 3600)
    dst = {"on": False}

    def localtime(seconds=None):
        return time.struct_time((2026, 7, 1, 0, 0, 0, 0, 182, int(dst["on"])))

    monkeypatch.setattr(time, "localtime", localtime)
    return dst


def test_a_moment_goes_on_the_line_scale_and_back(zone) -> None:
    moment = 1_761_716_129_587
    assert lines.to_line_scale(moment, summer_time=False) == moment + 5 * 3_600_000
    assert lines.to_epoch(lines.to_line_scale(moment, False), False) == moment
    zone["on"] = True
    assert lines.to_line_scale(moment, summer_time=False) == moment + 5 * 3_600_000
    assert lines.to_line_scale(moment, summer_time=True) == moment + 6 * 3_600_000
    assert lines.to_epoch(lines.to_line_scale(moment, True), True) == moment


def test_lines_are_read_each_in_its_encoding() -> None:
    rider = "15#" + chr(0x0418) + "#"
    data = (
        b"\xef\xbb\xbf1#0 0:0:1.000#nextLap#\r\n"
        + b"\n  \n"
        + rider.encode("cp1251")
        + b"\n2#\xff\x98#\n3#0 0:0:3.000#nextLap#"
    )
    assert lines.text_lines(data) == [
        "1#0 0:0:1.000#nextLap#",
        rider,
        "2#\xff\x98#",
        "3#0 0:0:3.000#nextLap#",
    ]


def test_the_source_offset_is_the_line_moment_less_the_video_moment() -> None:
    moment = 1_761_716_129_587
    line_ms = lines.to_line_scale(moment + 2500, False)
    assert lines.source_offset(line_ms, moment, False) == 2500
