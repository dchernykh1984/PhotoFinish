"""Crossing lines and their times, as every chronometer of the set writes them.

A line is ``number#time#action#``. The time is ``D H:M:S[.mmm]``: days since
1970-01-01 in local standard time, one hour later with the desktop chronometer's
summer-time option while daylight saving is on; hours, minutes and seconds not
zero-padded, milliseconds always three digits when present. The arithmetic is
ChronometerPython's ``models.format_time`` / ``parse_time``, so both read a line
the same way.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

_TIME = re.compile(r"(\d+) (\d{1,2}):(\d{1,2}):(\d{1,2})(?:\.(\d{3}))?", re.ASCII)
_HOUR_MS = 3_600_000
_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class Crossing:
    """A line as read: its number, its time on the line's scale, its action."""

    text: str
    number: str
    ms: int | None
    action: str


def parse_time(text: str) -> int | None:
    """Milliseconds of ``D H:M:S[.mmm]`` on its own scale, or None if it is not one."""
    m = _TIME.fullmatch(text.strip())
    if not m:
        return None
    days, hours, minutes, seconds = (int(g) for g in m.groups()[:4])
    if hours > 23 or minutes > 59 or seconds > 59:
        return None
    millis = int(m.group(5) or 0)
    return ((days * 24 + hours) * 60 + minutes) * 60_000 + seconds * 1000 + millis


def scale_time(ms: int) -> str:
    """``D H:M:S.mmm`` of milliseconds on the line scale: the inverse of parse_time."""
    days, rem = divmod(ms, 86_400_000)
    hours, rem = divmod(rem, _HOUR_MS)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{days} {hours}:{minutes}:{seconds}.{millis:03d}"


def parse_line(text: str) -> Crossing:
    """A crossing line; its time is None when it has none a chronometer would write."""
    fields = text.split("#")
    time_ms = parse_time(fields[1]) if len(fields) > 1 else None
    return Crossing(text, fields[0], time_ms, fields[2] if len(fields) > 2 else "")


def format_line(number: str, ms: int, action: str) -> str:
    return f"{number}#{scale_time(ms)}#{action}#"


def to_line_scale(epoch_ms: int, summer_time: bool) -> int:
    """A moment (Unix ms) on the line scale, as the desktop chronometer writes it."""
    summer = summer_time and bool(time.localtime(epoch_ms / 1000).tm_isdst)
    return epoch_ms - time.timezone * 1000 + (_HOUR_MS if summer else 0)


def source_offset(line_ms: int, moment: int, summer_time: bool) -> int:
    """What, added to the video's moment of a passing, gives the moment the timing
    source wrote for it in its line (Unix ms both)."""
    return to_epoch(line_ms, summer_time) - moment


def to_epoch(line_ms: int, summer_time: bool) -> int:
    """The moment (Unix ms) a line-scale time stands for: to_line_scale undone."""
    epoch = line_ms + time.timezone * 1000
    if summer_time and time.localtime((epoch - _HOUR_MS) / 1000).tm_isdst:
        epoch -= _HOUR_MS
    return epoch


def text_lines(data: bytes) -> list[str]:
    """The lines of a file's bytes, without a byte order mark. Each line is decoded
    on its own -- UTF-8, else cp1251 as the older C++ tools wrote, else Latin-1 --
    and blank lines are no crossings.
    """
    raw_lines = data.removeprefix(_BOM).split(b"\n")
    lines = (_decoded(raw.rstrip(b"\r")) for raw in raw_lines)
    return [line for line in lines if line.strip()]


def _decoded(raw: bytes) -> str:
    for encoding in ("utf-8", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")
