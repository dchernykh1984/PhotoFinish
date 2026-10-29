"""Cameras in step on a shared event (US6)."""

from __future__ import annotations

from app.shared_event import EVENT_S, SharedEvent, mark

CAMERAS = {"side", "front", "card"}


def test_the_first_mark_sets_the_moment_the_others_take_their_offsets() -> None:
    event, offset = mark(None, "side", 10_000, 10_000, 0.0, CAMERAS)
    assert (event, offset) == (SharedEvent("side", 10_000, 0.0), None)
    event, offset = mark(event, "front", 0, 8_766, 5.0, CAMERAS)
    assert offset == 1_234  # front's frame shown at side's moment
    assert event is not None
    event, offset = mark(event, "card", 0, 11_000, 9.0, CAMERAS)
    assert (event, offset) == (None, -1_000)  # every camera aligned: forgotten


def test_a_mark_on_the_same_camera_or_after_a_while_begins_a_new_event() -> None:
    event, _ = mark(None, "side", 10_000, 10_000, 0.0, CAMERAS)
    event, offset = mark(event, "side", 12_000, 12_000, 1.0, CAMERAS)
    assert (event, offset) == (SharedEvent("side", 12_000, 1.0), None)
    later = 1.0 + EVENT_S + 1
    event, offset = mark(event, "front", 3_600_000, 3_600_000, later, CAMERAS)
    assert (event, offset) == (SharedEvent("front", 3_600_000, later), None)
