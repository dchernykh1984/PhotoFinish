"""What may stop a phone's stream, as the window shows it under the recording banner.

The readings PhotoFinish Camera's keyframes carry (specs/005-phone-status), each as
a small icon and a number with how worrying it is: battery, heat, Wi-Fi, power
saver, frames dropped for the network, lenses asked for that it does not stream. A
reading the phone did not give is left out.
"""

from __future__ import annotations

import math
from typing import Any

from app.cameras import LENSES

OK, WARN, BAD = "ok", "warn", "bad"
STALE_MS = 5_000  # older than this, a status is the last one heard, not the phone now

BATTERY, PLUGGED = "\U0001f50b", chr(0x26A1)
HEAT, HOT = "\U0001f321", "\U0001f525"
WIFI, SAVER, DROPPED = "\U0001f4f6", "\U0001f343", chr(0x23EC)
LEFT = "\U0001f6ab"
DEGREES = chr(0xB0) + "C"
THERMAL = {2: "warm", 3: "hot", 4: "critical", 5: "emergency", 6: "shutting down"}


def readings(status: dict[str, Any]) -> list[tuple[str, str]]:
    """The status's readings in the order shown, each its text and its level."""
    found: list[tuple[str, str]] = []
    battery = _number(status.get("battery"))
    if battery is not None:
        charging = status.get("charging") == "1"
        text = f"{BATTERY} {battery:.0f}%" + (f" {PLUGGED}" if charging else "")
        level = OK if charging else _level(-battery, -25, -10)
        found.append((text, level))
    temp = _number(status.get("temp"))
    if temp is not None:
        found.append((f"{HEAT} {temp:.0f}{DEGREES}", _level(temp, 40, 45)))
    thermal = _number(status.get("thermal"))
    if thermal is not None and thermal >= 2:
        name = THERMAL.get(int(thermal), THERMAL[6])
        found.append((f"{HOT} {name}", WARN if thermal < 3 else BAD))
    wifi = _number(status.get("wifi"))
    if wifi is not None:
        found.append((f"{WIFI} {wifi:.0f} dBm", _level(-wifi, 70, 80)))
    if status.get("saver") == "1":
        found.append((f"{SAVER} power saver", WARN))
    dropped = _number(status.get("dropped"))
    if dropped:
        found.append((f"{DROPPED} {dropped:.0f} frames dropped", WARN))
    left = [LENSES.get(code, code) for code in sorted(lenses_left(status))]
    if left:  # its camera records nothing: the phone would not run it so
        found.append((f"{LEFT} {', '.join(left)} left out", WARN))
    return found


def lenses_left(status: dict[str, Any]) -> set[str]:
    """The lenses, by their codes, the phone was asked for and does not stream."""
    return {code for code in str(status.get("left", "")).split(",") if code}


def stale(status: dict[str, Any], now_ms: int) -> bool:
    """The status is no longer the phone's now: none heard for STALE_MS by this
    computer's clock, or heard on the far side of that clock set back -- until the
    phone's next."""
    heard = _number(status.get("heard_ms"))
    return heard is None or abs(now_ms - heard) > STALE_MS


def _level(value: float, warn: float, bad: float) -> str:
    """WARN from ``warn`` up, BAD from ``bad`` up."""
    return BAD if value >= bad else WARN if value >= warn else OK


def _number(value: object) -> float | None:
    """A reading as written, as a number; None when it is not one -- nor a finite
    one: what comes over the network is not to stop the window."""
    try:
        number = float(str(value)) if value is not None else None
    except ValueError:
        return None
    return number if number is not None and math.isfinite(number) else None
