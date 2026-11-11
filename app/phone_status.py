"""What may stop a phone's stream, as the window shows it under the recording banner.

The readings PhotoFinish Camera's keyframes carry (specs/005-phone-status), each as
a small icon and a number with how worrying it is: battery, heat, Wi-Fi, power
saver, frames dropped for the network. A reading the phone did not give is left out.
"""

from __future__ import annotations

import math
from typing import Any

OK, WARN, BAD = "ok", "warn", "bad"
STALE_MS = 5_000  # older than this, a status is the last one heard, not the phone now

BATTERY, PLUGGED = "\U0001f50b", chr(0x26A1)
HEAT, HOT = "\U0001f321", "\U0001f525"
WIFI, SAVER, DROPPED = "\U0001f4f6", "\U0001f343", chr(0x23EC)
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
    return found


def stale(status: dict[str, Any], now_ms: int) -> bool:
    """The status is no longer the phone's now: none heard for STALE_MS -- or this
    computer's clock was set back past it, which the recorder's steady clock that
    timed the status does not follow."""
    at = _number(status.get("at_ms"))
    return at is None or abs(now_ms - at) > STALE_MS


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
