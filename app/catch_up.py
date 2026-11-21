"""What a phone still holds for a camera, as the camera's line says it (specs/009).

PhotoFinish Camera says, with each keyframe it sends, how much video it holds for the
camera -- kept through a slow network or a break, or since the app or the phone
started again -- as ``unsent_ms``, the span of it. The line says how much there is, a
bar of what has come since the phone began falling behind, and, while the phone
catches up, about when the rest will be in. Less than SAID_MS held is the stream's
own pace, and says nothing.
"""

from __future__ import annotations

import collections
import math
from typing import Any

from app import phone_status

SAID_MS = 2_000
LOOK_BACK_MS = 60_000  # the estimate's: a minute of what the phone said
RECENT_MS = 10_000  # and falling over these last seconds too: a rise lately says none
FULL, EMPTY = chr(0x2588), chr(0x2591)
CELLS = 10
MINUTE_MS = 60_000


class CatchUp:
    """One camera's: the most the phone held since it began falling behind, and
    what it said it held lately, when this computer heard it."""

    def __init__(self) -> None:
        self.peak = 0
        self.said: collections.deque[tuple[int, int]] = collections.deque()

    def line(self, status: object, now_ms: int) -> str:
        """What the phone holds for the camera, as its line says it: "" for little --
        or for a status that is no table, from a heartbeat of another version. A
        status not heard for a while -- the phone gone quiet -- is told as last heard,
        with no estimate: nothing comes in meanwhile."""
        readings: dict[str, Any] = status if isinstance(status, dict) else {}
        held = _number(readings.get("unsent_ms"))
        heard = _number(readings.get("heard_ms"))
        if held is None or heard is None or held < SAID_MS:
            self.peak = 0
            self.said.clear()
            return ""
        if self.said and held > self.said[-1][1] + SAID_MS < self.peak:
            # Behind again after catching up a while: the bar measures this break.
            self.peak = held
            self.said.clear()
        if not self.said or self.said[-1][0] != heard:
            self.said.append((heard, held))
        while self.said and self.said[0][0] < heard - LOOK_BACK_MS:
            self.said.popleft()
        self.peak = max(self.peak, held)
        done = 1 - held / self.peak
        cells = round(done * CELLS)
        bar = FULL * cells + EMPTY * (CELLS - cells)
        text = f"{span(held)} of video on the phone {bar} {done:.0%}"
        if phone_status.stale(readings, now_ms):
            return text + ", as last heard"
        return text + self._estimate(held)

    def _estimate(self, held: int) -> str:
        """About when the rest is in, by how fast what it holds fell over the minute
        looked back on: nothing while it does not fall -- over the minute, nor over
        its last RECENT_MS, where a minute's fall would hide the phone falling behind
        again."""
        (first_at, first), (last_at, last) = self.said[0], self.said[-1]
        lately = [h for at, h in self.said if at <= last_at - RECENT_MS]
        then = lately[-1] if lately else first
        if last_at <= first_at or last >= first or last >= then:
            return ""
        left = held * (last_at - first_at) / (first - last)
        if left < MINUTE_MS:
            return ", in under a minute"
        return f", in about {math.ceil(left / MINUTE_MS)} min"


def span(ms: int) -> str:
    """``ms`` of video as a clock says it: M:SS, from an hour H:MM:SS."""
    seconds = max(ms, 0) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _number(value: object) -> int | None:
    """A reading as a whole number, read as the phone's other readings are."""
    found = phone_status.number(value)
    return None if found is None else int(found)
