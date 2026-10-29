"""A camera's recorded frames: found by time, decoded, in time to be seen."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import av
import pytest

from app import paths, session
from app.decoder import Decoder
from app.recorder import run
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import read_time, render
from app.video_index import Gap, VideoIndex
from tests.test_segments import make_h264

START = 1_761_716_129_587
ON_CI = bool(os.environ.get("CI"))


def record(folder: Path, start: int, frames: int, step: int = 33) -> None:
    writer = SegmentWriter(folder, fps=30)
    for k in range(frames):
        writer.write(render(start + k * step, 640, 360), start + k * step)
    writer.close()


def test_frames_are_found_by_time_and_decoded(tmp_path: Path) -> None:
    record(tmp_path, START, 70)
    index = VideoIndex(tmp_path)
    assert index.nearest(START) is None
    assert index.refresh()
    assert not index.refresh()
    assert len(index) == 70
    assert index.nearest(START - 1000) == 0
    assert index.nearest(START + 10**6) == 69
    assert index.nearest(START + 16) == 0  # as near to both: the earlier
    assert index.nearest(START + 17) == 1
    decoder = Decoder()
    for place in (0, 1, 2, 45, 46, 31, 69, 0):
        frame = index.frame(place)
        assert frame.ms == START + place * 33
        decoded = decoder.decode(frame.path, frame.pts)
        assert decoded is not None
        assert read_time(decoded.to_ndarray(format="rgb24")) == frame.ms
    assert index.frame(-5) == index.frame(0)
    assert decoder.decode(index.frame(69).path, 10**6) is None
    decoder.close()


def test_segments_closed_later_are_added_and_kept_in_time_order(tmp_path: Path) -> None:
    index = VideoIndex(tmp_path)
    record(tmp_path, START, 40)
    index.refresh()
    record(tmp_path, START + 5000, 10)
    assert index.refresh()
    assert len(index) == 50
    early = tmp_path / "20000101-000000-9999"  # named late, holding the earliest frame
    early.with_suffix(".times").write_text(f"0 {START - 1000}\n")
    early.with_suffix(".mkv").write_bytes(b"")
    (tmp_path / "20000101-000000-9998.mkv").write_bytes(b"")  # no times yet
    assert index.refresh()
    assert index.frame(0).path == early.with_suffix(".mkv")
    assert list(index.ms) == sorted(index.ms)


def test_a_cameras_own_stream_is_indexed_in_display_order(tmp_path: Path) -> None:
    make_h264(tmp_path / "camera.mp4", 40)
    folder = tmp_path / "cam1"
    writer = SegmentWriter(folder, fps=30)
    with av.open(str(tmp_path / "camera.mp4")) as container:
        stream = container.streams.video[0]
        unit = float(stream.time_base or 0) * 1000
        for packet in container.demux(stream):
            if packet.pts is not None:
                writer.write_packet(packet, START + round(packet.pts * unit))
        writer.close()
    index = VideoIndex(folder)
    index.refresh()
    assert list(index.ms) == sorted(index.ms)
    decoder = Decoder()
    frame = index.frame(5)
    decoded = decoder.decode(frame.path, frame.pts)
    assert decoded is not None
    assert read_time(decoded.to_ndarray(format="rgb24")) == START + 5 * 33
    decoder.close()


def test_gaps_are_read_as_the_recorder_writes_them(tmp_path: Path) -> None:
    index = VideoIndex(tmp_path)
    index.refresh()
    assert index.gaps == []
    gaps = tmp_path / "gaps.txt"
    gaps.write_text("1000 2000 restart\nbroken line\n")
    index.refresh()
    assert index.gaps == [Gap(1000, 2000, "restart")]
    with gaps.open("a") as f:
        f.write("3000 9000 reconnect\n")
    index.refresh()
    assert index.gaps[-1] == Gap(3000, 9000, "reconnect")


def test_a_frame_is_shown_within_two_seconds_of_its_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-006, the first half: the test camera recorded, the window polling."""
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    camera = {"id": "cam1", "connection": "test", "settings": {"fps": 30}}
    session.save({**session.DEFAULTS, "cameras": [camera]})
    folder = tmp_path / "video" / "cam1"
    recorder = threading.Thread(target=run, args=("cam1",))
    recorder.start()
    index, late = VideoIndex(folder), []
    try:
        until = time.monotonic() + 4
        while time.monotonic() < until:
            seen = len(index)
            index.refresh()
            now = time.time_ns() // 1_000_000
            late += [now - int(ms) for ms in index.ms[seen:]]
            time.sleep(0.5)
    finally:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "stop.request").touch()
        recorder.join(timeout=30)
    assert len(late) > 60
    assert max(late) <= (3000 if ON_CI else 2000)


def test_a_seek_in_an_hour_of_recording_shows_its_frame_at_once(
    tmp_path: Path,
) -> None:
    """SC-006, the second half: an hour of one-second segments, a frame far in."""
    record(tmp_path / "one", START, 31)
    (segment,) = (tmp_path / "one").glob("*-*-*.mkv")
    folder = tmp_path / "cam1"
    folder.mkdir()
    times = segment.with_suffix(".times").read_text().split()
    pts = times[0::2]
    for second in range(3600):
        name = folder / f"20261029-{second // 60:04d}{second % 60:02d}-{second:04d}"
        os.link(segment, name.with_suffix(".mkv"))
        moments = [str(START + second * 1000 + int(p)) for p in pts]
        lines = "".join(f"{p} {ms}\n" for p, ms in zip(pts, moments, strict=True))
        name.with_suffix(".times").write_text(lines)
    started = time.perf_counter()
    index = VideoIndex(folder)
    index.refresh()
    assert len(index) == 3600 * 31
    loaded = time.perf_counter() - started
    decoder = Decoder()
    started = time.perf_counter()
    place = index.nearest(START + 2950 * 1000 + 500)
    assert place is not None
    frame = index.frame(place)
    decoded = decoder.decode(frame.path, frame.pts)
    shown = time.perf_counter() - started
    decoder.close()
    assert decoded is not None
    assert read_time(decoded.to_ndarray(format="rgb24")) == START + 495  # its picture
    assert shown <= (2.0 if ON_CI else 0.5)
    assert loaded <= (20.0 if ON_CI else 5.0)
