"""Recording into short segments, each with the time of every frame."""

from __future__ import annotations

import contextlib
import errno
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import av
import numpy as np
import pytest

from app import files
from app.recorder import segments as segments_module
from app.recorder.segments import SegmentWriter, fraction, in_ms
from app.recorder.testcam import read_time, render

START = 1_761_716_129_587
NAME = re.compile(r"\d{8}-\d{6}-\d{4}")
ROOT = Path(__file__).resolve().parents[1]
KILLED = """
import os, sys
from pathlib import Path
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import render
writer = SegmentWriter(Path(sys.argv[1]), fps=30)
for k in range(int(sys.argv[2])):
    ms = int(sys.argv[3]) + k * 33
    writer.write(render(ms, 640, 360), ms)
os._exit(1)  # killed: nothing closed, nothing flushed on the way out
"""


def record(writer: SegmentWriter, start: int, frames: int, step: int = 33) -> None:
    for k in range(frames):
        writer.write(render(start + k * step, 640, 360), start + k * step)


def segments(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.mkv") if NAME.fullmatch(p.stem))


def killed_while_recording(folder: Path, frames: int, start: int = START) -> None:
    """A recorder process killed after ``frames`` frames."""
    run = [sys.executable, "-c", KILLED, str(folder), str(frames), str(start)]
    subprocess.run(run, cwd=ROOT, check=False)  # noqa: S603 - this interpreter


def packets(path: Path) -> list[int]:
    """The pts of the whole packets in a segment, a cluster cut short aside."""
    found: list[int] = []
    with av.open(str(path)) as video:
        try:
            found.extend(
                p.pts for p in video.demux(video=0) if p.size and p.pts is not None
            )
        except av.error.InvalidDataError:
            pass
    return found


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


def test_a_killed_recorder_leaves_its_open_segment_on_disk(tmp_path: Path) -> None:
    killed_while_recording(tmp_path, 20)  # under a second: the segment still open
    lines = (tmp_path / "current.times").read_text().splitlines()
    assert [int(line.split()[1]) for line in lines] == [
        START + k * 33 for k in range(20)
    ]
    assert len(packets(tmp_path / "current.mkv")) >= 20 - 4  # all but 0.1 s


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


def test_a_restart_shows_the_frames_a_crash_left_whole_and_marks_the_gap(
    tmp_path: Path,
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 70)
    writer.close()  # three segments closed
    killed_while_recording(tmp_path, 20, start=START + 5000)
    again = SegmentWriter(tmp_path, fps=30)
    recovered = segments(tmp_path)[-1]
    kept = times(recovered)
    assert len(kept) >= 20 - 4  # all but the last 0.1 s
    assert [ms for _, ms in kept] == [START + 5000 + k * 33 for k in range(len(kept))]
    assert packets(recovered) == [pts for pts, _ in kept]  # a file that ends well
    with av.open(str(recovered)) as video:
        assert sum(1 for _ in video.decode(video=0)) == len(kept)
    assert (tmp_path / "segments.txt").read_text().split()[-1] == recovered.stem
    assert again.segments == len(segments(tmp_path)) == 4
    assert not list(tmp_path.glob("current.*"))
    assert {p.suffix for p in tmp_path.glob("crashed-*")} == {".mkv", ".times"}
    record(again, START + 9000, 3)
    again.close()
    gaps = (tmp_path / "gaps.txt").read_text().splitlines()
    assert gaps[-1] == f"{kept[-1][1]} {START + 9000} restart"


def test_a_times_line_a_kill_cut_short_is_left_out(tmp_path: Path) -> None:
    killed_while_recording(tmp_path, 20)
    left = tmp_path / "current.times"
    lines = left.read_text().splitlines()
    left.write_text("".join(f"{line}\n" for line in lines[:3]) + lines[3][:-5])
    SegmentWriter(tmp_path, fps=30)
    (recovered,) = segments(tmp_path)
    assert [ms for _, ms in times(recovered)] == [START + k * 33 for k in range(3)]


class _CutShort:
    """A crashed segment read to three packets, then an end of file."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __enter__(self) -> _CutShort:
        return self

    def __exit__(self, *exc: object) -> None:
        self.inner.close()

    def demux(self, *streams: Any) -> Iterator[av.Packet]:
        for k, packet in enumerate(self.inner.demux(*streams)):
            if k == 3:
                raise av.error.EOFError(541478725, "End of file")
            yield packet


def test_a_crash_read_as_any_error_keeps_the_frames_before_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)
    real = av.open

    def opened(path: Any, *args: Any, **kwargs: Any) -> Any:
        found = real(path, *args, **kwargs)
        return _CutShort(found) if str(path).endswith("current.mkv") else found

    monkeypatch.setattr(segments_module.av, "open", opened)
    SegmentWriter(tmp_path, fps=30)
    (recovered,) = segments(tmp_path)
    assert len(times(recovered)) == 3


def test_a_recovery_that_fails_keeps_what_the_crash_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)

    def full(path: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(segments_module, "write_in_one_step", full)
    SegmentWriter(tmp_path, fps=30)
    assert segments(tmp_path) == []
    (kept,) = tmp_path.glob("crashed-*.times")
    assert len(kept.read_text().splitlines()) == 20  # every frame's time, kept
    assert not (tmp_path / "recovered.mkv").exists()  # no second copy on a full disk


def test_a_close_a_crash_cut_between_its_renames_is_finished(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    writer.close()
    (closed,) = segments(tmp_path)
    closed.replace(tmp_path / "current.mkv")  # the times renamed, the video not yet
    (tmp_path / "segments.txt").unlink()  # nor listed
    (tmp_path / "closing.name").write_text(closed.stem)  # the name close() wrote first
    again = SegmentWriter(tmp_path, fps=30)
    assert segments(tmp_path) == [closed]
    assert (tmp_path / "segments.txt").read_text().split() == [closed.stem]
    assert again.segments == 1
    assert not list(tmp_path.glob("crashed-*"))


def test_a_video_never_takes_the_name_of_times_whose_frames_it_lacks(
    tmp_path: Path,
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    writer.close()
    (closed,) = segments(tmp_path)
    closed.unlink()  # its video deleted for room: its times are left
    (tmp_path / "current.mkv").write_bytes(b"")  # a kill before the first frame
    SegmentWriter(tmp_path, fps=30)
    assert not closed.exists()
    assert segments(tmp_path) == []


def test_a_cut_close_finds_its_own_times_among_others_alike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = SegmentWriter(tmp_path, fps=30)
    record(earlier, START + 3_600_000, 5)  # before the clock was set back an hour
    earlier.close()
    (other,) = segments(tmp_path)
    other.unlink()  # its video deleted for room: its times, alike, are left
    hour_ago = time.time() - 3600
    os.utime(other.with_suffix(".times"), (hour_ago, hour_ago))
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    real = Path.replace

    def held(self: Path, target: Any) -> Path:
        if self.name == "current.mkv":
            raise OSError("held by a reader")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", held)
    with pytest.raises(OSError):
        writer.close()
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)
    (own,) = segments(tmp_path)
    assert times(own)[0] == (0, START)  # its own times, not the other's
    assert not other.exists()


def test_a_recovery_killed_before_its_copy_had_its_name_is_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)
    real = Path.replace

    def killed(self: Path, target: Any) -> Path:
        if self.name == "recovered.mkv":
            raise SystemExit(1)  # killed: no handler runs
        return real(self, target)

    monkeypatch.setattr(Path, "replace", killed)
    with pytest.raises(SystemExit):
        SegmentWriter(tmp_path, fps=30)
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)
    (recovered,) = segments(tmp_path)
    assert len(times(recovered)) >= 20 - 4
    assert (tmp_path / "segments.txt").read_text().split() == [recovered.stem]
    assert not (tmp_path / "recovered.mkv").exists()


def test_the_times_of_an_open_gops_leading_frames_are_read(tmp_path: Path) -> None:
    left = tmp_path / "current.times"
    left.write_text(f"-40 {START - 40}\n0 {START}\n40 {START + 40}\n80 x\n120")
    assert segments_module.frame_times(left) == {
        -40: START - 40,
        0: START,
        40: START + 40,
    }  # a line not two numbers, and the last one cut short, left out


def test_a_crash_kept_aside_halfway_is_kept_under_one_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "current.mkv").write_bytes(b"")  # nothing whole to show
    (tmp_path / "current.times").write_text(f"0 {START}\n")
    ticks = iter(range(START * 1_000_000, 2 * START * 1_000_000, 10**9))
    monkeypatch.setattr(segments_module.time, "time_ns", lambda: next(ticks))
    real = Path.replace

    def held(self: Path, target: Any) -> Path:
        if self.name == "current.mkv":
            raise OSError("held by a reader")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", held)
    with pytest.raises(OSError):
        SegmentWriter(tmp_path, fps=30)  # the times went aside, the video not
    monkeypatch.setattr(Path, "replace", real)
    SegmentWriter(tmp_path, fps=30)  # a second later
    stamps = {p.stem for p in tmp_path.glob("crashed-*")}
    assert len(stamps) == 1
    assert {p.suffix for p in tmp_path.glob("crashed-*")} == {".mkv", ".times"}


def test_two_crashes_kept_aside_in_one_millisecond_are_both_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(segments_module.time, "time_ns", lambda: START * 1_000_000)
    for frames in ("0 1\n", "0 2\n"):
        (tmp_path / "current.mkv").write_bytes(b"")
        (tmp_path / "current.times").write_text(frames)
        segments_module._keep_aside(tmp_path)
    kept = sorted(p.read_text() for p in tmp_path.glob("crashed-*.times"))
    assert kept == ["0 1\n", "0 2\n"]  # neither written over by the other
    assert len(list(tmp_path.glob("crashed-*.mkv"))) == 2


def test_a_crash_video_alone_never_joins_times_once_kept_aside_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "current.times").write_text(f"0 {START}\n")  # times, no video
    real = Path.unlink

    def killed(self: Path, missing_ok: bool = False) -> None:
        if self.name == "crashed.name" and self.exists():
            raise SystemExit(1)  # killed before it forgot the stamp
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", killed)
    with contextlib.suppress(SystemExit):
        segments_module._keep_aside(tmp_path)
    monkeypatch.undo()
    (tmp_path / "current.mkv").write_bytes(b"")  # a later crash, its video alone
    segments_module._keep_aside(tmp_path)
    assert len({p.stem for p in tmp_path.glob("crashed-*")}) == 2  # kept apart


def test_a_crash_video_alone_takes_no_times_another_crash_left_alone(
    tmp_path: Path,
) -> None:
    (tmp_path / "crashed-1000.times").write_text(f"0 {START}\n")  # an older version's
    (tmp_path / "current.mkv").write_bytes(b"")  # killed before its times were opened
    SegmentWriter(tmp_path, fps=30)
    assert not (tmp_path / "crashed-1000.mkv").exists()
    assert len(list(tmp_path.glob("crashed-*.mkv"))) == 1


def test_a_video_takes_no_times_written_long_before_it(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    writer.close()
    (closed,) = segments(tmp_path)
    hour_ago = time.time() - 3600
    os.utime(closed.with_suffix(".times"), (hour_ago, hour_ago))
    closed.replace(tmp_path / "current.mkv")  # a video alike: same frames, now
    SegmentWriter(tmp_path, fps=30)
    assert not closed.exists()  # not given the old times' name


def test_a_recovery_killed_before_it_wrote_its_name_is_done_again_from_the_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)

    def killed(path: Path, data: bytes) -> None:
        raise SystemExit(1)  # killed as the times were to be written

    monkeypatch.setattr(segments_module, "write_in_one_step", killed)
    with pytest.raises(SystemExit):
        SegmentWriter(tmp_path, fps=30)
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)
    (recovered,) = segments(tmp_path)
    assert [ms for _, ms in times(recovered)][:3] == [START, START + 33, START + 66]
    assert (tmp_path / "segments.txt").read_text().split() == [recovered.stem]
    assert not (tmp_path / "recovered.mkv").exists()


def test_a_crash_that_killed_the_recorder_as_it_was_read_is_kept_aside_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)

    def killed(left: Path, copy: Path, frames: dict[int, int]) -> None:
        raise SystemExit(1)  # the file brought the reader down, libav and all

    monkeypatch.setattr(segments_module, "_copy_whole", killed)
    with pytest.raises(SystemExit):
        SegmentWriter(tmp_path, fps=30)
    writer = SegmentWriter(tmp_path, fps=30)  # the next start: not brought down
    assert writer.segments == 0
    assert {p.suffix for p in tmp_path.glob("crashed-*")} == {".mkv", ".times"}
    assert not (tmp_path / "current.mkv").exists()
    monkeypatch.undo()
    killed_while_recording(tmp_path, 20, start=START + 60_000)  # a later crash
    SegmentWriter(tmp_path, fps=30)
    assert len(segments(tmp_path)) == 1  # read as any other


def test_a_crash_read_to_an_error_it_said_is_not_marked_as_one_that_kills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "current.mkv").write_bytes(b"")  # killed before its first cluster
    (tmp_path / "current.times").write_text(f"0 {START}\n")
    marked: list[bool] = []
    real = segments_module._keep_aside

    def aside(folder: Path) -> None:
        marked.append((folder / segments_module.READING).exists())
        real(folder)

    monkeypatch.setattr(segments_module, "_keep_aside", aside)
    SegmentWriter(tmp_path, fps=30)
    assert marked == [False]  # a kill as it goes aside leaves no crash unread


def test_a_recovery_whose_name_cannot_be_read_a_moment_is_kept_not_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)

    def held(folder: Path, name: str) -> None:
        raise OSError("held by a reader")

    monkeypatch.setattr(segments_module, "_name_recovery", held)
    SegmentWriter(tmp_path, fps=30)  # recovered, the crash aside; its copy unnamed
    monkeypatch.undo()
    real = Path.read_text

    def unreadable(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == segments_module.RECOVERED_NAME:
            raise PermissionError("held by a scanner")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    SegmentWriter(tmp_path, fps=30)  # the name it is to take not readable just now
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)
    (recovered,) = segments(tmp_path)
    assert times(recovered)[0][1] == START  # the copy kept, named at last


def test_a_recovery_named_but_its_name_not_forgotten_is_listed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)
    real = Path.unlink
    refused: list[Path] = []

    def held(self: Path, missing_ok: bool = False) -> None:
        if self.name == segments_module.RECOVERED_NAME and self.exists():
            if len(refused) < 2:
                refused.append(self)
                raise PermissionError("held by a scanner")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held)
    SegmentWriter(tmp_path, fps=30)  # named; the name it took not forgotten
    SegmentWriter(tmp_path, fps=30)  # nor at first as the next one starts
    listed = (tmp_path / "segments.txt").read_text().split()
    assert listed == [p.stem for p in segments(tmp_path)]  # once


def test_a_recovery_that_finds_the_disk_full_leaves_the_crash_for_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)

    def full(path: Path, data: bytes) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(segments_module, "write_in_one_step", full)
    with pytest.raises(OSError) as raised:
        SegmentWriter(tmp_path, fps=30)
    assert raised.value.errno == errno.ENOSPC  # for the recorder: disk_full
    assert (tmp_path / "current.mkv").exists()  # not given up
    assert not (tmp_path / segments_module.RECOVERED_MKV).exists()  # its room back
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)  # room made
    assert len(segments(tmp_path)) == 1


def test_a_recovery_not_yet_named_is_never_written_over_by_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, later = tmp_path / "cam", tmp_path / "later"
    killed_while_recording(folder, 20, start=START - 60_000)
    killed_while_recording(later, 20, start=START)  # the next crash, kept apart

    def held(folder: Path, name: str) -> None:
        raise OSError("held by a reader")

    monkeypatch.setattr(segments_module, "_name_recovery", held)
    SegmentWriter(folder, fps=30)  # recovered; its copy cannot take its name yet
    for left in later.glob("current.*"):
        left.replace(folder / left.name)
    SegmentWriter(folder, fps=30)  # and still cannot, as the next crash is seen to
    monkeypatch.undo()
    SegmentWriter(folder, fps=30)
    (recovered,) = segments(folder)
    assert times(recovered)[0][1] == START - 60_000  # the first crash's frames
    assert len(list(folder.glob("crashed-*.mkv"))) == 2  # the next one's kept


def test_a_segment_never_takes_the_name_a_recovery_is_still_to_take(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 10, start=START - 400)  # in START's second

    def held(folder: Path, name: str) -> None:
        raise OSError("held by a reader")

    monkeypatch.setattr(segments_module, "_name_recovery", held)
    writer = SegmentWriter(tmp_path, fps=30)  # recovered; its copy not named yet
    record(writer, START, 5)  # a segment begun in that same second
    writer.close()
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)
    found = sorted(times(segment)[0][1] for segment in segments(tmp_path))
    assert found == [START - 400, START]  # each with its own frames, none written over


def test_a_segment_never_takes_the_name_of_times_left_alone(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    writer.close()
    (closed,) = segments(tmp_path)
    alone = closed.with_suffix(".times")
    kept = alone.read_text()
    closed.unlink()  # its video gone aside: its times alone, and unlisted
    (tmp_path / "segments.txt").unlink()
    again = SegmentWriter(tmp_path, fps=30)
    record(again, START + 100, 3)  # a clock set back: other frames, that second
    again.close()
    assert alone.read_text() == kept


def test_a_recovery_killed_after_it_wrote_its_name_is_finished_as_meant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20, start=START - 60_000)  # an earlier crash
    SegmentWriter(tmp_path, fps=30)  # recovered, its files kept aside
    killed_while_recording(tmp_path, 20, start=START)  # and another

    def killed(folder: Path) -> None:
        raise SystemExit(1)  # killed as the crash was to go aside

    monkeypatch.setattr(segments_module, "_keep_aside", killed)
    with pytest.raises(SystemExit):
        SegmentWriter(tmp_path, fps=30)
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)
    earlier, later = segments(tmp_path)  # no frame twice
    assert times(earlier)[0][1] == START - 60_000
    assert times(later)[0][1] == START  # its own times, not the earlier crash's
    assert not list(tmp_path.glob("recovered.*"))


def test_a_recovery_killed_after_its_name_knows_its_source_by_its_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)
    left = tmp_path / "current.times"
    left.write_text(f"-500 {START - 500}\n" + left.read_text())  # no packet whole

    def killed(folder: Path) -> None:
        raise SystemExit(1)  # killed as the crash was to go aside

    monkeypatch.setattr(segments_module, "_keep_aside", killed)
    with pytest.raises(SystemExit):
        SegmentWriter(tmp_path, fps=30)
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)
    assert len(segments(tmp_path)) == 1  # its frames once, not recovered again


def test_a_segment_whose_video_will_not_close_lets_its_times_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    segment = writer._open
    assert segment is not None

    class Refusing:
        def mux(self, packet: object) -> None:
            pass

        def close(self) -> None:
            raise av.FFmpegError(5, "trailer refused")

    real, segment.container = segment.container, Refusing()  # type: ignore[assignment]
    with pytest.raises(av.FFmpegError):
        writer.close()
    assert segment.times.closed
    real.close()


def test_a_name_a_kill_cut_short_in_the_list_counts_for_no_segment(
    tmp_path: Path,
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    writer.close()
    (tmp_path / "segments.txt").open("a").write("2026110")  # cut mid-name
    assert SegmentWriter(tmp_path, fps=30).segments == 1


@pytest.mark.parametrize(
    ("ticks", "ms"), [(45, 1), (44, 0), (-44, 0), (-45, -1), (-46, -1), (-135, -2)]
)
def test_a_pts_is_rounded_to_ms_as_the_muxer_rounds_it(ticks: int, ms: int) -> None:
    from fractions import Fraction

    assert segments_module.in_ms(ticks, Fraction(1, 90000)) == ms


def test_a_slow_close_cut_between_its_renames_is_finished_by_its_name(
    tmp_path: Path,
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    writer.close()
    (closed,) = segments(tmp_path)
    minute_ago = time.time() - 60  # its times written long before its video moved
    os.utime(closed.with_suffix(".times"), (minute_ago, minute_ago))
    closed.replace(tmp_path / "current.mkv")
    (tmp_path / "closing.name").write_text(closed.stem)
    SegmentWriter(tmp_path, fps=30)
    assert segments(tmp_path) == [closed]
    assert not (tmp_path / "closing.name").exists()


def test_a_recovery_left_unnamed_while_recording_hides_no_later_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)

    def broken(self: object) -> None:
        raise av.FFmpegError(5, "mux failed")

    monkeypatch.setattr(segments_module._Encoded, "close", broken)
    with pytest.raises(av.FFmpegError):
        writer.close()
    monkeypatch.undo()
    real = Path.replace

    def held(self: Path, target: Any) -> Path:
        if self.name == "recovered.mkv":
            raise OSError("held by a scanner")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", held)
    record(writer, START + 5000, 20)  # recovered while recording, its copy unnamed
    monkeypatch.undo()
    SegmentWriter(tmp_path, fps=30)  # killed with that open: the next start
    first, second = segments(tmp_path)
    assert times(first)[0][1] == START
    assert times(second)[0][1] == START + 5000  # the later crash, not hidden


def test_what_a_crash_left_with_no_whole_frame_is_kept_aside(tmp_path: Path) -> None:
    (tmp_path / "current.mkv").write_bytes(b"")
    (tmp_path / "current.times").write_text(f"0 {START}\n")
    writer = SegmentWriter(tmp_path, fps=30)
    assert {p.suffix for p in tmp_path.glob("crashed-*")} == {".mkv", ".times"}
    assert writer.segments == 0
    assert segments(tmp_path) == []
    assert not (tmp_path / "recovered.mkv").exists()


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
    assert len(kept.read_text().splitlines()) == 5  # the five frames, kept as they were
    writer.close()
    recovered, last = segments(tmp_path)
    assert [ms for _, ms in times(recovered)][:3] == [START, START + 33, START + 66]
    assert times(last) == [(0, START + 5000), (33, START + 5033)]
    assert writer.segments == 2


def test_a_close_that_fails_at_its_renames_counts_its_segment_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    real = Path.replace

    def held(self: Path, target: Any) -> Path:
        if self.name == "current.times":
            raise OSError("held by a reader")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", held)
    with pytest.raises(OSError):
        writer.close()
    monkeypatch.undo()
    record(writer, START + 5000, 2)
    writer.close()
    assert writer.segments == len((tmp_path / "segments.txt").read_text().split()) == 2


def test_a_segment_recovered_while_recording_is_listed_in_order_though_refused_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)

    def broken(self: object) -> None:
        raise av.FFmpegError(5, "mux failed")

    monkeypatch.setattr(segments_module._Encoded, "close", broken)
    with pytest.raises(av.FFmpegError):
        writer.close()
    monkeypatch.undo()
    real = segments_module.append
    refused: list[bytes] = []

    def once(path: Path, data: bytes) -> None:
        if path.name == "segments.txt" and not refused:
            refused.append(data)
            raise OSError("held by a reader")
        real(path, data)

    monkeypatch.setattr(segments_module, "append", once)
    with pytest.raises(OSError):
        record(writer, START + 5000, 1)  # the recovered segment's listing refused
    record(writer, START + 5100, 2)
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    assert listed == [p.stem for p in segments(tmp_path)]  # both, in their order
    assert writer.segments == 2


def test_a_recovery_named_late_while_recording_is_listed_while_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: object) -> None:
        raise av.FFmpegError(5, "mux failed")

    def held(folder: Path, name: str) -> None:
        raise OSError("held by a reader")

    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    monkeypatch.setattr(segments_module._Encoded, "close", broken)
    with pytest.raises(av.FFmpegError):
        writer.close()  # a close that fails, recovered at the next frame
    monkeypatch.undo()
    monkeypatch.setattr(segments_module, "_name_recovery", held)
    record(writer, START + 5000, 5)  # its copy cannot take its name yet
    monkeypatch.undo()
    monkeypatch.setattr(segments_module._Encoded, "close", broken)
    with pytest.raises(av.FFmpegError):
        writer.close()  # and another
    monkeypatch.undo()
    record(writer, START + 7000, 2)  # the first copy named now, the second made
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    assert listed == [p.stem for p in segments(tmp_path)]  # all three, as they came
    assert writer.segments == 3


def forgetting_refused_once(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """The first unlink of ``name`` refused: a scanner holds the file a moment."""
    real = Path.unlink
    refused: list[Path] = []

    def held(self: Path, missing_ok: bool = False) -> None:
        if self.name == name and not refused:
            refused.append(self)
            raise PermissionError("held by a scanner")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held)


def test_a_close_whose_name_cannot_be_forgotten_is_listed_all_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    forgetting_refused_once(monkeypatch, "closing.name")
    writer.close()
    record(writer, START + 5000, 2)
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    assert listed == [p.stem for p in segments(tmp_path)]  # both, as they closed
    assert writer.segments == 2


def test_a_cut_close_finished_whose_name_cannot_be_forgotten_is_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    real = Path.replace

    def refused(self: Path, target: Any) -> Path:
        if self.name == "current.mkv":
            raise OSError("held by a reader")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", refused)
    with pytest.raises(OSError):
        writer.close()  # the times renamed, the video not
    monkeypatch.undo()
    forgetting_refused_once(monkeypatch, "closing.name")
    record(writer, START + 5000, 2)  # that close finished, its name still held
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    assert listed == [p.stem for p in segments(tmp_path)]
    assert writer.segments == 2


def test_a_cut_close_refused_again_waits_for_its_name_never_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    real = Path.replace

    def refused(self: Path, target: Any) -> Path:
        named = segments_module.NAMED.fullmatch(Path(target).stem)
        if self.name == "current.mkv" and named:  # let go just after each try
            raise OSError("held by a reader")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", refused)
    with pytest.raises(OSError):
        writer.close()  # the times renamed, the video not
    with pytest.raises(OSError):
        record(writer, START + 5000, 1)  # refused again: no frame over it
    monkeypatch.undo()
    record(writer, START + 5100, 2)
    writer.close()
    first, last = segments(tmp_path)
    assert len(times(first)) == 5  # its video and its times under one name
    assert not list(tmp_path.glob("crashed-*"))
    assert (tmp_path / "segments.txt").read_text().split() == [first.stem, last.stem]


def test_a_recovery_left_unnamed_is_named_and_listed_at_the_next_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: object) -> None:
        raise av.FFmpegError(5, "mux failed")

    def held(folder: Path, name: str) -> None:
        raise OSError("held by a reader")

    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    monkeypatch.setattr(segments_module._Encoded, "close", broken)
    with pytest.raises(av.FFmpegError):
        writer.close()
    monkeypatch.undo()
    monkeypatch.setattr(segments_module, "_name_recovery", held)
    record(writer, START + 5000, 5)  # recovered; its copy cannot take its name yet
    monkeypatch.undo()
    writer.close()  # every close after it goes well
    record(writer, START + 7000, 2)
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    assert sorted(listed) == [p.stem for p in segments(tmp_path)]  # in this run
    assert writer.segments == 3


def test_a_crash_read_whole_is_recovered_though_its_mark_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_while_recording(tmp_path, 20)
    forgetting_refused_once(monkeypatch, segments_module.READING)
    SegmentWriter(tmp_path, fps=30)
    assert len(segments(tmp_path)) == 1  # the copy kept, its mark cleared as it went


def test_a_close_that_named_its_times_only_is_finished_while_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 5)
    real = Path.replace

    def held(self: Path, target: Any) -> Path:
        if self.name == "current.mkv":
            raise OSError("held by a reader")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", held)
    with pytest.raises(OSError):
        writer.close()  # the times renamed, the video not
    monkeypatch.undo()
    record(writer, START + 5000, 2)
    writer.close()
    first, last = segments(tmp_path)
    assert len(times(first)) == 5  # all of it, not set aside
    assert (tmp_path / "segments.txt").read_text().split() == [first.stem, last.stem]
    assert not list(tmp_path.glob("crashed-*"))


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


def test_a_restart_after_a_garbled_segment_records_on_from_the_one_before(
    tmp_path: Path,
) -> None:
    # A power cut can leave a segment's times garbled: the recorder still starts,
    # or the camera would record nothing for the rest of the race.
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 40)
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    (tmp_path / f"{listed[-1]}.times").write_bytes(b"0 \xff\xfe\n")
    before = (tmp_path / f"{listed[-2]}.times").read_text().split()[-1]
    restarted = SegmentWriter(tmp_path, fps=30)
    assert restarted._before_ms == int(before)


def test_a_restart_after_a_segment_of_frames_sent_again_takes_the_one_before(
    tmp_path: Path,
) -> None:
    # A segment a phone's frames sent again made lists none of them (specs/007): the
    # run before's newest frame is in the segment before it.
    writer = SegmentWriter(tmp_path, fps=30)
    record(writer, START, 40)
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    (tmp_path / f"{listed[-1]}.times").write_text("")  # all of it sent again
    before = (tmp_path / f"{listed[-2]}.times").read_text().split()[-1]
    restarted = SegmentWriter(tmp_path, fps=30)
    assert restarted._before_ms == int(before)
    assert restarted.gap_reason == "restart"


def test_a_segment_the_list_refused_is_listed_with_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SegmentWriter(tmp_path, fps=30)
    refused = [OSError(5, "Input/output error")]

    def listing(path: Path, data: bytes) -> None:
        if refused and path.name == "segments.txt":
            raise refused.pop()
        files.append(path, data)

    monkeypatch.setattr(segments_module, "append", listing)
    with pytest.raises(OSError):
        record(writer, START, 40)  # the first segment closed, its name refused
    record(writer, START + 2000, 10)  # the recorder goes on, as it does
    writer.close()
    listed = (tmp_path / "segments.txt").read_text().split()
    assert listed == [p.stem for p in segments(tmp_path)]
    assert len(listed) == 2


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


def with_sound(path: Path, seconds: int) -> None:
    """A phone's stream with its sound (specs/013): H.264 without B-frames, a keyframe
    a second, and AAC, mono, 48 kHz, each piece where it was captured."""
    with av.open(str(path), "w", format="matroska") as out:
        video = out.add_stream("libx264", rate=30, options={"g": "30", "bf": "0"})
        video.width, video.height, video.pix_fmt = 640, 360, "yuv420p"
        sound = out.add_stream("aac", rate=48000)
        sound.layout = "mono"
        heard = 0
        for k in range(30 * seconds):
            frame = av.VideoFrame.from_ndarray(render(START + k * 33, 640, 360))
            frame.pts = k
            for packet in video.encode(frame):
                out.mux(packet)
            while heard * 1024 * 1000 < (k + 1) * 33 * 48000:  # sound to this frame
                tone = np.full((1, 1024), 0.1 if heard % 2 else -0.1, np.float32)
                piece = av.AudioFrame.from_ndarray(tone, format="fltp", layout="mono")
                piece.sample_rate, piece.pts = 48000, heard * 1024
                for packet in sound.encode(piece):
                    out.mux(packet)
                heard += 1
        for stream in (video, sound):
            for packet in stream.encode(None):
                out.mux(packet)


def recorded_with_sound(
    source: Path, folder: Path, again: int = 0
) -> tuple[SegmentWriter, list[int]]:
    """The stream into a writer at its own moments, from START; the sound's moments
    given. The last ``again`` pieces of sound sent again, as after a loss."""
    writer = SegmentWriter(folder, fps=30)
    moments: list[int] = []
    sent: list[tuple[av.Packet, int]] = []
    with av.open(str(source)) as container:
        for packet in container.demux():
            if packet.pts is None or packet.dts is None:
                continue
            ms = START + in_ms(packet.pts or 0, fraction(packet.time_base))
            if packet.stream.type == "audio":
                writer.write_audio(packet, ms)
                if writer.frames:  # before the first frame: no segment to keep it
                    moments.append(ms)
                    sent.append((packet, ms))
            else:
                writer.write_packet(packet, ms)
        if again:  # a new connection, as after a loss, sending them again
            writer.hung_up()
        for packet, ms in sent[len(sent) - again :] if again else []:
            writer.write_audio(packet, ms)
    writer.close()
    return writer, moments


def sound_moments(path: Path) -> list[int]:
    """A segment's pieces of sound, each placed by the frame its timestamp is nearest
    in its times, as the readers place them."""
    listed = times(path)
    found = []
    with av.open(str(path)) as container:
        audio = container.streams.audio[0]
        for packet in container.demux(audio):
            if packet.pts is None:
                continue
            pts = in_ms(packet.pts or 0, fraction(audio.time_base))
            frame_pts, frame_ms = min(listed, key=lambda pair: abs(pair[0] - pts))
            found.append(frame_ms + pts - frame_pts)
    return found


def test_a_streams_sound_is_kept_beside_its_video_on_its_moments(
    tmp_path: Path,
) -> None:
    with_sound(tmp_path / "phone.mkv", 3)
    folder = tmp_path / "cam1"
    _, moments = recorded_with_sound(tmp_path / "phone.mkv", folder)
    closed = segments(folder)
    assert len(closed) == 3
    kept = sorted(ms for path in closed for ms in sound_moments(path))
    assert kept == sorted(moments)  # every piece once, where it was heard
    for path in closed:
        listed = [pts for pts, _ in times(path)]
        assert min(listed) >= segments_module.LEAD_MS  # no timestamp below 0
        with av.open(str(path)) as container:  # the frames listed are the file's
            assert [f.pts for f in container.decode(video=0)] == sorted(listed)


def test_sound_heard_before_a_segments_first_frame_goes_into_it_unshifted(
    tmp_path: Path,
) -> None:
    # A piece captured before the keyframe that opens a segment, come after it: a
    # Matroska muxer given a negative timestamp shifts every stream (specs/013).
    with_sound(tmp_path / "phone.mkv", 2)
    folder = tmp_path / "cam1"
    writer = SegmentWriter(folder, fps=30)
    with av.open(str(tmp_path / "phone.mkv")) as container:
        demuxed = [p for p in container.demux() if p.pts is not None]
        video = [p for p in demuxed if p.stream.type == "video"]
        audio = [p for p in demuxed if p.stream.type == "audio"]
        first = video[30]  # the second second's keyframe
        assert first.is_keyframe
        at = in_ms(first.pts or 0, fraction(first.time_base))
        early = [p for p in audio if in_ms(p.pts or 0, fraction(p.time_base)) < at][-3:]
        writer.write_packet(first, START + at)
        for packet in early:
            writer.write_audio(
                packet, START + in_ms(packet.pts or 0, fraction(packet.time_base))
            )
        for packet in video[31:40]:
            writer.write_packet(
                packet, START + in_ms(packet.pts or 0, fraction(packet.time_base))
            )
    writer.close()
    (path,) = segments(folder)
    listed = [pts for pts, _ in times(path)]
    with av.open(str(path)) as container:
        assert [f.pts for f in container.decode(video=0)] == listed
    assert sound_moments(path) == [
        START + in_ms(p.pts or 0, fraction(p.time_base)) for p in early
    ]


def test_sound_sent_again_is_kept_once_and_sound_before_any_frame_none(
    tmp_path: Path,
) -> None:
    with_sound(tmp_path / "phone.mkv", 2)
    folder = tmp_path / "cam1"
    _, moments = recorded_with_sound(tmp_path / "phone.mkv", folder, again=20)
    kept = sorted(ms for path in segments(folder) for ms in sound_moments(path))
    assert kept == sorted(moments)
    lone = SegmentWriter(tmp_path / "cam2", fps=30)
    with av.open(str(tmp_path / "phone.mkv")) as container:
        audio = next(p for p in container.demux() if p.stream.type == "audio")
        lone.write_audio(audio, START)  # no frame yet: no segment to keep it in
    lone.close()
    assert not segments(tmp_path / "cam2")


KILLED_WITH_SOUND = """
import os, sys
from pathlib import Path
import av
from app.recorder.segments import SegmentWriter, fraction, in_ms
writer = SegmentWriter(Path(sys.argv[1]), fps=30)
with av.open(sys.argv[2]) as container:
    for packet in container.demux():
        if packet.pts is None:
            continue
        ms = int(sys.argv[3]) + in_ms(packet.pts, fraction(packet.time_base))
        if packet.stream.type == "audio":
            writer.write_audio(packet, ms)
        else:
            writer.write_packet(packet, ms)
os._exit(1)  # killed: nothing closed, nothing flushed on the way out
"""


def test_a_crash_keeps_the_sound_it_left_whole_with_its_frames(tmp_path: Path) -> None:
    with_sound(tmp_path / "phone.mkv", 1)  # one segment, left open by the kill
    folder = tmp_path / "cam1"
    run = [
        sys.executable,
        "-c",
        KILLED_WITH_SOUND,
        str(folder),
        str(tmp_path / "phone.mkv"),
        str(START),
    ]
    subprocess.run(run, cwd=ROOT, check=False)  # noqa: S603 - this interpreter
    assert (folder / "current.mkv").exists()
    (name,) = segments_module.recover(folder)
    with av.open(str(folder / f"{name}.mkv")) as container:
        assert container.streams.audio
        heard = [p for p in container.demux(container.streams.audio[0]) if p.size]
    assert len(heard) > 30  # most of a second of it, a cluster cut short aside
    assert (folder / segments_module.SOUND).read_text().split() == [name]


class RefusingSound:
    """A file of a segment's whose muxer refuses its sound's packets."""

    def __init__(self, real: Any) -> None:
        self.real = real

    def __enter__(self) -> RefusingSound:
        return self

    def __exit__(self, *exc: object) -> None:
        self.real.__exit__(*exc)

    def add_stream_from_template(self, template: Any) -> Any:
        return self.real.add_stream_from_template(template)

    def mux(self, packet: av.Packet) -> None:
        if packet.stream.type == "audio":
            raise av.FFmpegError(22, "refused")
        self.real.mux(packet)


def test_a_crash_whose_sound_the_copy_refuses_keeps_its_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A refused sound costs the sound alone: never the frames a crash left whole.
    with_sound(tmp_path / "phone.mkv", 1)
    folder = tmp_path / "cam1"
    run = [
        sys.executable,
        "-c",
        KILLED_WITH_SOUND,
        str(folder),
        str(tmp_path / "phone.mkv"),
        str(START),
    ]
    subprocess.run(run, cwd=ROOT, check=False)  # noqa: S603 - this interpreter
    real = av.open

    def opened(path: Any, *args: Any, **kwargs: Any) -> Any:
        made = real(path, *args, **kwargs)
        copy = str(path).endswith(segments_module.RECOVERED_MKV)
        return RefusingSound(made) if copy else made

    monkeypatch.setattr(segments_module.av, "open", opened)
    (name,) = segments_module.recover(folder)
    monkeypatch.undo()
    assert len(segments_module.frame_times(folder / f"{name}.times")) > 20


def test_a_cameras_sound_matroska_will_not_hold_costs_the_sound_alone(
    tmp_path: Path,
) -> None:
    # An IP camera's G.711 (specs/013): kept only when it is AAC, the video whole.
    source = tmp_path / "ipcam.mov"
    with av.open(str(source), "w", format="mov") as out:
        video = out.add_stream("libx264", rate=30, options={"g": "30", "bf": "0"})
        video.width, video.height, video.pix_fmt = 160, 96, "yuv420p"
        heard = out.add_stream("pcm_mulaw", rate=8000)
        heard.layout = "mono"
        for k in range(45):
            frame = av.VideoFrame.from_ndarray(render(START + k * 33, 160, 96))
            frame.pts = k
            for packet in video.encode(frame):
                out.mux(packet)
            piece = av.AudioFrame.from_ndarray(
                np.zeros((1, 267), np.int16), format="s16", layout="mono"
            )
            piece.sample_rate, piece.pts = 8000, k * 267
            for packet in heard.encode(piece):
                out.mux(packet)
        for stream in (video, heard):
            for packet in stream.encode(None):
                out.mux(packet)
    folder = tmp_path / "cam1"
    writer = SegmentWriter(folder, fps=30)
    with av.open(str(source)) as container:
        for packet in container.demux():
            if packet.pts is None:
                continue
            ms = START + in_ms(packet.pts, fraction(packet.time_base))
            if packet.stream.type == "audio":
                writer.write_audio(packet, ms)
            else:
                writer.write_packet(packet, ms)
    writer.close()
    assert writer.frames == 45
    for path in segments(folder):
        with av.open(str(path)) as container:
            assert not container.streams.audio


KILLED_SILENT = """
import os, sys
from pathlib import Path
import av
from app.recorder.segments import SegmentWriter, fraction, in_ms
writer = SegmentWriter(Path(sys.argv[1]), fps=30)
n = 0
with av.open(sys.argv[2]) as container:
    for packet in container.demux():
        if packet.pts is None or packet.stream.type == "audio":
            continue  # its sound declared, no piece of it: a microphone gone silent
        ms = int(sys.argv[3]) + in_ms(packet.pts, fraction(packet.time_base))
        writer.write_packet(packet, ms)
        n += 1
        if n == 25:
            break
import time
time.sleep(0.3)
os._exit(1)  # killed: nothing closed, nothing flushed on the way out
"""


def test_a_crash_keeps_the_frames_of_a_stream_whose_sound_went_silent(
    tmp_path: Path,
) -> None:
    # Matroska's interleaving waited for a piece of every stream before writing any:
    # a sound gone silent held the frames back, and a crash lost the segment whole.
    with_sound(tmp_path / "phone.mkv", 1)
    folder = tmp_path / "cam1"
    run = [
        sys.executable,
        "-c",
        KILLED_SILENT,
        str(folder),
        str(tmp_path / "phone.mkv"),
        str(START),
    ]
    subprocess.run(run, cwd=ROOT, check=False)  # noqa: S603 - this interpreter
    (name,) = segments_module.recover(folder)
    assert len(packets(folder / f"{name}.mkv")) >= 20  # all but the last 0.1 s


def test_sound_placed_a_little_back_within_a_connection_is_kept(tmp_path: Path) -> None:
    # A frame placed late moves the pieces after it by as much: within a connection
    # the phone sends each piece once, so none is taken for one sent again.
    with_sound(tmp_path / "phone.mkv", 2)
    folder = tmp_path / "cam1"
    writer = SegmentWriter(folder, fps=30)
    kept: list[int] = []
    with av.open(str(tmp_path / "phone.mkv")) as container:
        for n, packet in enumerate(p for p in container.demux() if p.pts is not None):
            ms = START + in_ms(packet.pts or 0, fraction(packet.time_base))
            if packet.stream.type == "video":
                writer.write_packet(packet, ms)
                continue
            jitter = -15 if n % 7 == 0 else 0  # now and then 15 ms back
            writer.write_audio(packet, ms + jitter)
            if writer.frames:
                kept.append(ms)
    writer.close()
    heard = [ms for path in segments(folder) for ms in sound_moments(path)]
    assert len(heard) == len(kept)


def test_a_piece_of_sound_out_of_order_is_passed_over_never_muxed(
    tmp_path: Path,
) -> None:
    # A muxer handed a time gone back refuses it: the recorder would end with it.
    with_sound(tmp_path / "phone.mkv", 1)
    folder = tmp_path / "cam1"
    writer = SegmentWriter(folder, fps=30)
    with av.open(str(tmp_path / "phone.mkv")) as container:
        demuxed = [p for p in container.demux() if p.pts is not None]
        heard = [p for p in demuxed if p.stream.type == "audio"]
        for packet in demuxed:
            ms = START + in_ms(packet.pts or 0, fraction(packet.time_base))
            if packet.stream.type == "video":
                writer.write_packet(packet, ms)
            else:
                writer.write_audio(packet, ms)
                if packet is heard[20]:
                    writer.write_audio(heard[10], ms + 100)  # an older one, placed on
    writer.close()
    assert len(segments(folder)) == 1


def test_a_piece_of_sound_the_muxer_refuses_costs_the_sound_never_the_video(
    tmp_path: Path,
) -> None:
    with_sound(tmp_path / "phone.mkv", 2)
    folder = tmp_path / "cam1"
    writer = SegmentWriter(folder, fps=30)

    class Refusing:
        """The segment's video, refusing its sound."""

        def __init__(self, real: Any, audio: Any) -> None:
            self.real, self.audio = real, audio

        def mux(self, packet: av.Packet) -> None:
            if packet.stream is self.audio:
                raise av.FFmpegError(22, "refused")
            self.real.mux(packet)

        def close(self) -> None:
            self.real.close()

    with av.open(str(tmp_path / "phone.mkv")) as container:
        for packet in container.demux():
            if packet.pts is None:
                continue
            ms = START + in_ms(packet.pts, fraction(packet.time_base))
            if packet.stream.type == "video":
                writer.write_packet(packet, ms)
                opened = writer._open
                assert isinstance(opened, segments_module._Remuxed)
                if not isinstance(opened.container, Refusing):
                    refusing = Refusing(opened.container, opened.audio)
                    opened.container = refusing  # type: ignore[assignment]
            else:
                assert not writer.write_audio(packet, ms)
    writer.close()
    assert writer.frames == 60


def test_a_segments_sound_is_listed_before_it_and_a_sound_list_refused_costs_it_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Listed first, a kill between the two leaves it to the recovery, which lists
    # its sound again; a sound list the disk refuses is no segment unclosed.
    with_sound(tmp_path / "phone.mkv", 3)
    folder = tmp_path / "cam1"
    real = segments_module.append
    order: list[str] = []

    def append(path: Path, data: bytes) -> None:
        order.append(path.name)
        if path.name == segments_module.SOUND and order.count(path.name) == 2:
            raise OSError("refused")  # the second segment's
        real(path, data)

    monkeypatch.setattr(segments_module, "append", append)
    writer, _ = recorded_with_sound(tmp_path / "phone.mkv", folder)
    names = [n for n in order if n in (segments_module.SOUND, segments_module.SEGMENTS)]
    assert names[:2] == [segments_module.SOUND, segments_module.SEGMENTS]
    assert len(segments(folder)) == writer.segments  # each closed, each listed


def test_the_segments_that_kept_sound_are_listed_beside_the_others(
    tmp_path: Path,
) -> None:
    # Whether a camera has sound, found without opening its hours of segments (013).
    with_sound(tmp_path / "phone.mkv", 2)
    folder = tmp_path / "cam1"
    recorded_with_sound(tmp_path / "phone.mkv", folder)
    listed = (folder / segments_module.SOUND).read_text().split()
    assert listed == [path.stem for path in segments(folder)]
    silent = tmp_path / "cam2"
    lone = SegmentWriter(silent, fps=30)
    record(lone, START, 40)
    lone.close()
    assert not (silent / segments_module.SOUND).exists()
    # Closed, and the lists lost to a kill before they took them: listed as it starts.
    (folder / segments_module.SEGMENTS).unlink()
    (folder / segments_module.SOUND).unlink()
    segments_module.recover(folder)
    assert (folder / segments_module.SOUND).read_text().split() == listed
