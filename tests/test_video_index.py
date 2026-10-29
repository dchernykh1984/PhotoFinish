"""A camera's recorded frames: found by time, decoded, in time to be seen."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import av
import pytest

from app import paths, session, video_index
from app.decoder import Decoder
from app.recorder import run
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import read_time, render
from app.video_index import FileIndex, Frame, Gap, VideoIndex
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
    early = tmp_path / "20000101-000000-9999"  # listed late, holding the earliest frame
    early.with_suffix(".times").write_text(f"0 {START - 1000}\n")
    early.with_suffix(".mkv").write_bytes(b"")
    late = tmp_path / "20000101-000000-9998"  # its times not readable yet
    late.with_suffix(".mkv").write_bytes(b"")
    with (tmp_path / "segments.txt").open("a") as f:
        f.write(f"{early.name}\n{late.name}\n")
    assert index.refresh()
    assert index.frame(0).path == early.with_suffix(".mkv")
    assert list(index.ms) == sorted(index.ms)
    late.with_suffix(".times").write_text(f"0 {START + 9000}\n")
    assert index.refresh()  # read once it could be
    assert index.frame(len(index) - 1).path == late.with_suffix(".mkv")


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
    listed = []
    for second in range(3600):
        name = folder / f"20261029-{second // 60:04d}{second % 60:02d}-{second:04d}"
        os.link(segment, name.with_suffix(".mkv"))
        moments = [str(START + second * 1000 + int(p)) for p in pts]
        lines = "".join(f"{p} {ms}\n" for p, ms in zip(pts, moments, strict=True))
        name.with_suffix(".times").write_text(lines)
        listed.append(name.name)
    (folder / "segments.txt").write_text("".join(f"{n}\n" for n in listed))
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


def camera_file(path: Path, frames: int, created: str | None = None) -> None:
    """A camera's own recording: 25 fps, the test camera's frames from START."""
    with av.open(str(path), "w") as container:
        if created is not None:
            container.metadata["creation_time"] = created
        stream = container.add_stream("mpeg4", rate=25)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
        for k in range(frames):
            frame = av.VideoFrame.from_ndarray(render(START + k * 40, 640, 360))
            frame.pts = k
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def read(index: FileIndex) -> bool:
    """The file's frames, once its own thread has read them."""
    until = time.monotonic() + 30
    while True:
        if index.refresh():
            return True
        reading = index._reading
        if reading is not None and not reading.is_alive() and index._handed:
            return False
        assert time.monotonic() < until, "timed out"
        time.sleep(0.01)


def test_a_cameras_own_file_is_placed_by_its_creation_time(tmp_path: Path) -> None:
    path = tmp_path / "DCIM0001.mp4"
    camera_file(path, 10, created="2025-10-29T05:35:29.000000Z")  # START, to the s
    written = path.read_bytes()
    index = FileIndex(path)
    assert read(index)
    assert not index.refresh()
    assert len(index) == 10
    assert index.ms[0] == START - 587
    assert list(index.ms[1:] - index.ms[:-1]) == [40] * 9
    decoder = Decoder()
    frame = index.frame(index.step(0, 7))
    decoded = decoder.decode(frame.path, frame.pts)
    assert decoded is not None
    assert read_time(decoded.to_ndarray(format="rgb24")) == START + 7 * 40
    decoder.close()
    assert path.read_bytes() == written  # never changed


def test_without_a_creation_time_a_file_ends_when_it_was_written(
    tmp_path: Path,
) -> None:
    path = tmp_path / "race.mkv"
    camera_file(path, 5)
    os.utime(path, ns=(START * 1_000_000, START * 1_000_000))
    index = FileIndex(path)
    read(index)
    assert list(index.ms) == [START - 160 + k * 40 for k in range(5)]
    assert video_index._created_ms("2025-10-29 05:35:29") == START - 587  # UTC
    assert video_index._created_ms(None) is None


def test_a_file_that_is_no_video_gives_no_frames(tmp_path: Path) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("not a video")
    assert not read(FileIndex(text))
    assert not read(FileIndex(tmp_path / "missing.mp4"))
    empty = tmp_path / "empty.mkv"
    with av.open(str(empty), "w") as container:
        stream = container.add_stream("mpeg4", rate=25)
        stream.width, stream.height, stream.pix_fmt = 64, 64, "yuv420p"
        container.start_encoding()  # a header, and not one frame
    index = FileIndex(empty)
    assert not read(index)
    assert len(index) == 0


def test_a_far_frame_of_a_long_file_is_sought_not_decoded_to(tmp_path: Path) -> None:
    path = tmp_path / "long.mkv"
    camera_file(path, 250)  # ten seconds at 25 fps
    index = FileIndex(path)
    assert read(index)
    decoder = Decoder()
    for place, seeks in ((0, 1), (1, 1), (10, 1), (240, 2), (241, 2), (5, 3)):
        frame = index.frame(place)
        decoded = decoder.decode(frame.path, frame.pts)
        assert decoded is not None
        assert read_time(decoded.to_ndarray(format="rgb24")) == START + place * 40
        assert decoder.seeks == seeks, place
    decoder.close()


def test_a_segment_listed_without_a_frame_adds_none(tmp_path: Path) -> None:
    record(tmp_path, START, 40)
    index = VideoIndex(tmp_path)
    index.refresh()
    empty = tmp_path / "20261029-235959-9999"
    empty.with_suffix(".times").write_text("")
    empty.with_suffix(".mkv").write_bytes(b"")
    with (tmp_path / "segments.txt").open("a") as f:
        f.write(empty.name + "\n")
    assert not index.refresh()
    assert len(index) == 40
    assert empty.with_suffix(".mkv") not in index.paths


def test_an_hour_of_segments_is_appended_without_copying_it_each_time(
    tmp_path: Path,
) -> None:
    import numpy as np

    index = VideoIndex(tmp_path)
    index.paths = [tmp_path / "a.mkv"]
    started = time.perf_counter()
    for second in range(3600):
        moments = START + second * 1000 + np.arange(30, dtype=np.int64) * 33
        index._append(moments, np.arange(30, dtype=np.int64), np.zeros(30, np.int32))
    assert time.perf_counter() - started < (5.0 if ON_CI else 2.0)
    assert len(index) == 108_000
    assert index.frame(107_999).ms == START + 3599 * 1000 + 29 * 33
    index._append(np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0, np.int32))
    assert len(index) == 108_000


def test_a_frame_is_found_again_after_the_frames_were_sorted_anew(
    tmp_path: Path,
) -> None:
    record(tmp_path, START, 40)
    index = VideoIndex(tmp_path)
    index.refresh()
    frame = index.frame(35)
    assert (index.generation, index.find(frame)) == (0, 35)
    record(tmp_path, START - 5000, 10)  # an earlier segment, listed late
    index.refresh()
    assert index.generation == 1
    assert index.find(frame) == 45
    assert index.frame(45) == frame
    assert index.find(Frame(tmp_path / "x.mkv", 0, 0)) is None
    assert index.find(Frame(frame.path, 10**9, 0)) is None
