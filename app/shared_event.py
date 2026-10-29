"""Cameras in step on an event they all show (US6): a flash, a hand wave.

The first camera the event is marked on sets its moment; each camera marked after
takes the offset that shows the event at that moment. Once every camera is aligned,
or EVENT_S after the first mark, the next mark begins a new event.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EVENT_S = 600  # an event not shown on the other cameras by then is forgotten


@dataclass
class SharedEvent:
    camera: str
    moment: int  # on the video's time
    since: float  # monotonic, when it was marked
    aligned: set[str] = field(default_factory=set)


def mark(
    event: SharedEvent | None,
    camera: str,
    moment: int,
    frame_ms: int,
    now: float,
    cameras: set[str],
) -> tuple[SharedEvent | None, int | None]:
    """The event after a mark on ``camera``, at its frame ``frame_ms`` shown at
    ``moment`` on the video's time; and the offset the camera takes, None when the
    mark begins an event."""
    if event is None or event.camera == camera or now - event.since > EVENT_S:
        return SharedEvent(camera, moment, now), None
    event.aligned.add(camera)
    every = event.aligned >= cameras - {event.camera}
    return (None if every else event), event.moment - frame_ms
