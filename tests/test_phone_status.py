"""The phone's readings and how worrying each is (specs/005-phone-status)."""

from __future__ import annotations

from app import phone_status
from app.phone_status import (
    BAD,
    BATTERY,
    DEGREES,
    DROPPED,
    HEAT,
    HOT,
    OK,
    PLUGGED,
    SAVER,
    WARN,
    WIFI,
)


def levels(status: dict[str, str]) -> list[str]:
    return [level for _, level in phone_status.readings(status)]


def test_a_charging_phone_in_good_shape_worries_no_one() -> None:
    status = {"battery": "57", "charging": "1", "temp": "34.5", "thermal": "0"}
    status |= {"saver": "0", "wifi": "-61", "dropped": "0"}
    assert phone_status.readings(status) == [
        (f"{BATTERY} 57% {PLUGGED}", OK),
        (f"{HEAT} 34{DEGREES}", OK),  # 34.5 rounds to the even 34
        (f"{WIFI} -61 dBm", OK),
    ]


def test_a_battery_running_out_is_amber_then_red_unless_it_charges() -> None:
    assert levels({"battery": "26", "charging": "0"}) == [OK]
    assert levels({"battery": "25", "charging": "0"}) == [WARN]
    assert levels({"battery": "10", "charging": "0"}) == [BAD]
    assert levels({"battery": "5", "charging": "1"}) == [OK]


def test_heat_wifi_saver_and_dropped_frames() -> None:
    assert levels({"temp": "40"}) == [WARN]
    assert levels({"temp": "45.2"}) == [BAD]
    assert phone_status.readings({"thermal": "2"}) == [(f"{HOT} warm", WARN)]
    assert phone_status.readings({"thermal": "9"}) == [(f"{HOT} shutting down", BAD)]
    assert levels({"thermal": "1"}) == []  # light: not worth a word
    assert levels({"wifi": "-70"}) == [WARN]
    assert levels({"wifi": "-80"}) == [BAD]
    assert phone_status.readings({"saver": "1"}) == [(f"{SAVER} power saver", WARN)]
    assert phone_status.readings({"dropped": "12"}) == [
        (f"{DROPPED} 12 frames dropped", WARN)
    ]


def test_a_reading_not_given_or_not_a_number_is_left_out() -> None:
    assert phone_status.readings({}) == []
    assert phone_status.readings({"battery": "full", "wifi": "", "x": "1"}) == []
    infinite = {"battery": "inf", "thermal": "inf", "temp": "nan", "wifi": "-1e999"}
    assert phone_status.readings(infinite) == []


def test_a_status_not_heard_for_five_seconds_is_stale() -> None:
    assert not phone_status.stale({"heard_ms": "1000"}, 6_000)
    assert phone_status.stale({"heard_ms": 1000}, 6_001)
    assert phone_status.stale({}, 0)
    assert phone_status.stale({"heard_ms": 10_000}, 4_000)  # the clock set back 6 s


def test_a_status_heard_now_is_fresh_with_the_recorder_s_clock_ahead() -> None:
    # The computer's clock set back 10 s: the recorder's steady clock stays ahead.
    assert not phone_status.stale({"at_ms": 20_000, "heard_ms": 10_000}, 10_500)
