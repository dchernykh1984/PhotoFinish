"""Recording into short segments, each with the time of every frame."""

from __future__ import annotations

import re
import time
from pathlib import Path

import av
import pytest

from app.recorder.segments import SegmentWriter
from app.recorder.testcam import read_time, render

START = 1_761_716_129_587
NAME = re.compile(r"\d{8}-\d{6}-\d{4}")


def record(writer: SegmentWriter, start: int, frames: int, step: int = 33) -> None:
    for k in range(frames):
        writer.write(render(start + k * step, 640, 360), start + k * step)


def segments(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.mkv") if NAME.fullmatch(p.stem))


def times(path: Path) -> list[tuple[int, int]]:
    lines = path.with_suffix(".times").read_text().splitlines()
    return [(int(pts), int(ms)) for pts, ms in (line.split() for line in lines)]


def test_frames_go_into_one_second_segments_with_their_times(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 150)
    assert len(segments(tmp_path)) == 4
    assert (tmp_path / "current.mkv").exists()
    writer.close()
    closed = segments(tmp_path)
    assert len(closed) == 5
    assert (writer.segments, writer.frames) == (5, 150)
    assert not (tmp_path / "current.mkv").exists()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(START / 1000))
    assert closed[0].stem == f"{stamp}-0001"
    for path in closed:
        frames = times(path)
        assert frames[-1][1] - frames[0][1] < 1000
        with av.open(str(path)) as container:
            packets = [p for p in container.demux(video=0) if p.pts is not None]
            assert packets[0].is_keyframe
        with av.open(str(path)) as container:
            decoded = [
                (f.pts, read_time(f.to_ndarray(format="rgb24")))
                for f in container.decode(video=0)
            ]
        assert decoded == frames
    assert not (tmp_path / "gaps.txt").exists()


def test_a_stretch_without_frames_is_a_gap(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 3)
    writer.write(render(START + 66 + 101, 640, 360), START + 66 + 101)
    writer.write(render(START + 66 + 101, 640, 360), START + 66 + 101)
    writer.close()
    assert (
        tmp_path / "gaps.txt"
    ).read_text() == f"{START + 66} {START + 167} no frames\n"
    assert writer.frames == 4


def test_a_restart_keeps_what_a_crash_left_and_marks_the_gap(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 70)
    writer.close()
    last = times(segments(tmp_path)[-1])[-1][1]
    record(writer, START + 5000, 10)
    del writer  # a crash: the open segment stays as it was
    again = SegmentWriter(tmp_path, fps=30)
    assert {p.suffix for p in tmp_path.glob("crashed-*")} == {".mkv", ".times"}
    record(again, START + 9000, 3)
    again.close()
    gaps = (tmp_path / "gaps.txt").read_text().splitlines()
    assert gaps[-1] == f"{last} {START + 9000} restart"
    assert len(segments(tmp_path)) == 4


@pytest.mark.parametrize("fps", [25, 29.97, 60])
def test_the_frame_rate_is_kept_as_the_stream_rate(tmp_path: Path, fps: float) -> None:
    writer = SegmentWriter(tmp_path, fps=fps)
    record(writer, START, 3, step=round(1000 / fps))
    writer.close()
    with av.open(str(segments(tmp_path)[0])) as container:
        assert container.streams.video[0].codec_context.name == "mpeg4"


def test_a_video_frame_is_written_as_it_comes(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    frame = av.VideoFrame.from_ndarray(render(START, 640, 360), format="rgb24")
    writer.write(frame.reformat(format="yuv420p"), START)
    writer.close()
    assert times(segments(tmp_path)[0]) == [(0, START)]


def test_closing_twice_or_onto_a_name_taken_loses_nothing(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    writer.close()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(START / 1000))
    (tmp_path / f"{stamp}-0001.mkv").write_bytes(b"kept")
    record(writer, START, 2)
    writer.close()
    assert (tmp_path / f"{stamp}-0001.mkv").read_bytes() == b"kept"
    assert times(tmp_path / f"{stamp}-0002.mkv") == [(0, START), (33, START + 33)]


def make_h264(path: Path, frames: int) -> None:
    """A camera's own stream: H.264 with B-frames, a keyframe a second."""
    with av.open(str(path), "w") as container:
        stream = container.add_stream(
            "libx264", rate=30, options={"g": "30", "bf": "2"}
        )
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
        for k in range(frames):
            frame = av.VideoFrame.from_ndarray(render(START + k * 33, 640, 360))
            frame.pts = k
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def test_a_cameras_packets_are_kept_from_its_first_keyframe_on(tmp_path: Path) -> None:
    make_h264(tmp_path / "camera.mp4", 150)
    folder = tmp_path / "cam1"
    writer = SegmentWriter(folder, fps=30)
    writer.write(render(START - 5000, 640, 360), START - 5000)  # was encoding before
    with av.open(str(tmp_path / "camera.mp4")) as container:
        stream = container.streams.video[0]
        unit = float(stream.time_base or 0) * 1000
        packets = list(container.demux(stream))
        assert packets[-1].pts is None  # the demuxer's last, empty packet
        for packet in packets[1:]:  # the stream joined after its first keyframe
            writer.write_packet(packet, START + round((packet.pts or 0) * unit))
        writer.close()
    assert writer.frames == 1 + 120
    closed = segments(folder)
    assert len(closed) == 5
    for path in closed[1:]:
        with av.open(str(path)) as container:
            packets = [p for p in container.demux(video=0) if p.pts is not None]
            assert packets[0].is_keyframe
        with av.open(str(path)) as container:
            decoded = [f.pts for f in container.decode(video=0)]
        assert decoded == sorted(pts for pts, _ in times(path))
        assert len(decoded) == 30


def test_a_segment_that_fails_to_close_is_kept_not_written_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.recorder import segments as written

    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)

    def broken(self: object) -> None:
        raise av.FFmpegError(5, "mux failed")

    monkeypatch.setattr(written._Encoded, "close", broken)
    with pytest.raises(av.FFmpegError):
        writer.close()
    monkeypatch.undo()
    record(writer, START + 5000, 2)
    (kept,) = tmp_path.glob("crashed-*.times")
    assert len(kept.read_text().splitlines()) == 5  # the five frames, kept
    writer.close()
    assert times(segments(tmp_path)[-1]) == [(0, START + 5000), (33, START + 5033)]


def test_closed_segments_are_listed_and_a_restart_lists_any_a_crash_missed(
    tmp_path: Path,
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 40)
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    assert listed == [p.stem for p in segments(tmp_path)]
    (tmp_path / "segments.txt").write_text(listed[0] + "\n")  # a crash lost the rest
    again = SegmentWriter(tmp_path, fps=30)
    assert (tmp_path / "segments.txt").read_text().split() == listed
    assert again.segments == len(listed)
    cut = listed[0][:9]  # killed while writing a name
    (tmp_path / "segments.txt").write_text(cut)
    SegmentWriter(tmp_path, fps=30)
    assert (tmp_path / "segments.txt").read_text().split() == [cut, *listed]
    with (tmp_path / "segments.txt").open("a") as f:
        f.write(cut + "\n")  # the last name cut short: the one before has the times
    restarted = SegmentWriter(tmp_path, fps=30)
    assert restarted._before_ms == START + 39 * 33


def test_a_restart_on_a_clock_set_back_records_rather_than_waits(
    tmp_path: Path,
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START + 600_000, 5)  # the run before, its clock ten minutes fast
    writer.close()
    again = SegmentWriter(tmp_path, fps=30)
    record(again, START, 5)  # the clock set right before the restart
    again.close()
    assert again.frames == 5
    assert not (tmp_path / "gaps.txt").exists()  # no gap backwards
