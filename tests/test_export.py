"""A camera's video as one file (specs/011-video-export)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import av
import numpy as np
import pytest

from app import export, video_index
from app.recorder.segments import SegmentWriter
from app.recorder.testcam import render
from tests.test_sound import START as HEARD
from tests.test_sound import recorded

START = 1_795_000_000_000


def record(folder: Path, start: int, frames: int, width: int = 320) -> None:
    """``frames`` frames 33 ms apart from ``start``, at ``width`` by 9/16 of it."""
    writer = SegmentWriter(folder, fps=30)
    for k in range(frames):
        writer.write(render(start + k * 33, width, width * 9 // 16), start + k * 33)
    writer.close()


def read(path: Path) -> tuple[str, list[int]]:
    """The file's codec and its frames' times, ms."""
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        times = [
            round(float(packet.pts * stream.time_base) * 1000)
            for packet in container.demux(stream)
            if packet.pts is not None
        ]
        return stream.codec_context.name, sorted(times)


def test_a_camera_s_pieces_make_one_file_timed_by_the_frames_moments(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "video" / "cam1"
    record(folder, START, 70)
    seen: list[tuple[int, int]] = []
    written = export.export(folder, tmp_path / "Side.mp4", lambda *a: seen.append(a))
    assert written == [tmp_path / "Side.mp4"]
    codec, times = read(written[0])
    assert codec == read(export.pieces(folder)[0])[0]  # copied, not encoded again
    assert times == [k * 33 for k in range(70)]
    assert seen[-1] == (len(export.pieces(folder)),) * 2
    assert not list(tmp_path.glob("*.part"))


def test_a_frame_its_piece_does_not_list_is_left_out_as_sent_again(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 20)
    times = next(folder.glob("2*.times"))
    lines = times.read_text().split("\n")
    times.write_text("\n".join(lines[:5] + lines[6:]))  # the sixth frame: not listed
    _, out = read(export.export(folder, tmp_path / "a.mp4")[0])
    assert len(out) == 19
    assert 5 * 33 not in out


def test_a_format_changed_goes_on_in_a_second_file(tmp_path: Path) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 40)
    record(folder, START + 5_000, 40, width=256)  # the phone set up again, smaller
    written = export.export(folder, tmp_path / "Side.mp4")
    assert written == [tmp_path / "Side.mp4", tmp_path / "Side-2.mp4"]
    assert read(written[1])[1][0] == 0  # each file's time begins at its first frame


def test_a_name_taken_gets_a_number_and_nothing_is_overwritten(tmp_path: Path) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 10)
    (tmp_path / "Side.mp4").write_bytes(b"the referee's")
    written = export.export(folder, tmp_path / "Side.mp4")
    assert written == [tmp_path / "Side (2).mp4"]
    assert (tmp_path / "Side.mp4").read_bytes() == b"the referee's"


def test_cancel_stops_the_export_and_removes_the_file_under_way(tmp_path: Path) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 70)
    done: list[int] = []
    with pytest.raises(export.CancelledError):
        export.export(
            folder,
            tmp_path / "Side.mp4",
            lambda d, _: done.append(d),
            cancelled=lambda: bool(done),
        )
    assert not list(tmp_path.glob("Side*"))


def test_a_failure_writing_removes_the_file_under_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 40)

    def full(*_: object) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(export._Out, "add", full)
    with pytest.raises(OSError, match="No space"):
        export.export(folder, tmp_path / "Side.mp4")
    assert not list(tmp_path.glob("Side*"))


def test_a_piece_that_cannot_be_read_is_skipped_the_rest_exported(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 70)
    broken = export.pieces(folder)[1]
    broken.write_bytes(b"not a video")
    skipped: list[Path] = []
    (written,) = export.export(folder, tmp_path / "Side.mp4", skipped=skipped)
    assert skipped == [broken]
    times = read(written)[1]
    assert times[0] == 0 and len(times) < 70  # the pieces before and after it


def test_the_files_done_before_a_cancel_are_told(tmp_path: Path) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 40)
    record(folder, START + 5_000, 40, width=256)
    written: list[Path] = []
    with pytest.raises(export.CancelledError):
        export.export(
            folder,
            tmp_path / "Side.mp4",
            cancelled=lambda: bool(written),
            written=written,
        )
    assert written == [tmp_path / "Side.mp4"]
    assert sorted(p.name for p in tmp_path.glob("Side*")) == ["Side.mp4"]


def test_a_piece_whose_times_are_lost_is_skipped_and_a_garbled_list_stops_nothing(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 70)
    lost = export.pieces(folder)[1]
    lost.with_suffix(".times").unlink()
    skipped: list[Path] = []
    assert len(export.export(folder, tmp_path / "Side.mp4", skipped=skipped)) == 1
    assert skipped == [lost]
    listed = folder / "segments.txt"
    listed.write_bytes(listed.read_bytes() + b"\xff\xfe\n")
    assert len(export.pieces(folder)) == 3


def test_nothing_recorded_exports_nothing(tmp_path: Path) -> None:
    assert export.export(tmp_path / "none", tmp_path / "x.mp4") == []


def h265_piece(folder: Path, frames: int) -> None:
    """A piece of H.265 as a phone's push leaves it: Matroska, its times beside it."""
    folder.mkdir(parents=True)
    name = "20261121-120000-0001"
    with av.open(str(folder / f"{name}.mkv"), "w", format="matroska") as out:
        stream = out.add_stream("libx265", rate=30)
        stream.width, stream.height, stream.pix_fmt = 192, 108, "yuv420p"
        stream.options = {"x265-params": "bframes=0:log-level=error"}
        lines = []
        for k in range(frames):
            frame = av.VideoFrame.from_ndarray(
                render(START + k * 33, 192, 108), "rgb24"
            )
            frame.pts = k
            for packet in stream.encode(frame.reformat(format="yuv420p")):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    with av.open(str(folder / f"{name}.mkv")) as back:
        s = back.streams.video[0]
        pts = sorted(
            round(float(p.pts * s.time_base) * 1000)
            for p in back.demux(s)
            if p.pts is not None
        )
    lines = [f"{p} {START + p}" for p in pts]
    (folder / f"{name}.times").write_text("\n".join(lines) + "\n")
    (folder / "segments.txt").write_text(name + "\n")


def test_h265_is_tagged_hvc1_as_quicktime_wants(tmp_path: Path) -> None:
    try:
        av.codec.Codec("libx265", "w")
    except av.codec.codec.UnknownCodecError:
        pytest.skip("no H.265 encoder here to make a piece with")
    h265_piece(tmp_path / "cam1", 12)
    (written,) = export.export(tmp_path / "cam1", tmp_path / "Tele.mp4")
    with av.open(str(written)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.name == "hevc"
        assert stream.codec_tag == "hvc1"
        assert len([p for p in container.demux(stream) if p.pts is not None]) == 12


def test_a_camera_has_video_once_a_piece_listed_is_there(tmp_path: Path) -> None:
    folder = tmp_path / "cam1"
    assert not export.has_video(folder)
    record(folder, START, 10)
    assert export.has_video(folder)
    for piece in export.pieces(folder):
        piece.unlink()
    assert not export.has_video(folder)


def test_a_second_export_names_its_parts_after_its_own_first_file(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 40)
    record(folder, START + 5_000, 40, width=256)
    export.export(folder, tmp_path / "Side.mp4")
    again = export.export(folder, tmp_path / "Side.mp4")
    assert again == [tmp_path / "Side (2).mp4", tmp_path / "Side (2)-2.mp4"]


def test_a_file_that_cannot_be_set_up_leaves_nothing_half_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 10)

    def refused(*_: object) -> None:
        raise ValueError("no such codec in MP4")

    monkeypatch.setattr(
        av.container.OutputContainer, "add_stream_from_template", refused
    )
    with pytest.raises(ValueError, match="no such codec"):
        export.export(folder, tmp_path / "Side.mp4")
    assert not list(tmp_path.glob("Side*"))


def test_after_a_piece_left_out_the_file_goes_on_at_a_keyframe(tmp_path: Path) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 70)
    first, broken, last = export.pieces(folder)
    broken.write_bytes(b"not a video")
    times = last.with_suffix(".times")
    times.write_text(
        "\n".join(times.read_text().split("\n")[1:])
    )  # its keyframe unlisted
    _, out = read(export.export(folder, tmp_path / "Side.mp4")[0])
    assert len(out) == len(first.with_suffix(".times").read_text().split()) // 2


def test_a_piece_listed_twice_is_exported_once_and_one_gone_is_told(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 70)
    listed = folder / "segments.txt"
    names = listed.read_text().split()
    listed.write_text("\n".join([*names, names[0], "not-a-piece"]) + "\n")
    export.pieces(folder)[1].unlink()  # gone from the disk
    skipped: list[Path] = []
    _, out = read(export.export(folder, tmp_path / "Side.mp4", skipped=skipped)[0])
    assert len(out) == len(set(out))
    assert len(skipped) == 1


def test_a_clock_set_back_goes_on_in_a_new_file_never_back_in_time(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START + 60_000, 40)
    record(folder, START, 40)  # the recorder's clock set back a minute
    written = export.export(folder, tmp_path / "Side.mp4")
    assert written == [tmp_path / "Side.mp4", tmp_path / "Side-2.mp4"]
    assert all(read(path)[1] == sorted(set(read(path)[1])) for path in written)


def test_frames_out_of_moment_order_as_b_frames_come_stay_in_one_file(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "cam1"
    record(folder, START, 70)
    times = export.pieces(folder)[0].with_suffix(".times")
    lines = times.read_text().split("\n")
    lines[3], lines[4] = (
        f"{lines[3].split()[0]} {lines[4].split()[1]}",
        f"{lines[4].split()[0]} {lines[3].split()[1]}",
    )  # the 4th frame's moment after the 5th's, in decode order: a B-frame's way
    times.write_text("\n".join(lines))
    written = export.export(folder, tmp_path / "Side.mp4")
    assert written == [tmp_path / "Side.mp4"]
    assert len(read(written[0])[1]) == 70


def test_a_camera_s_name_becomes_a_file_s() -> None:
    assert export.file_name('Mi 17: main/"wide"') == "Mi 17_ main_wide_"
    assert export.file_name("...") == "camera"
    assert export.file_name("aux") == "aux_"
    assert export.file_name("Aux.cam") == "Aux_.cam"  # AUX still, whatever follows
    assert export.file_name("NUL .x") == "NUL_.x"
    assert export.file_name("Con.1.2") == "Con_.1.2"
    assert export.file_name("Auxiliary") == "Auxiliary"
    assert export.file_name("COM0") == "COM0_"
    assert export.file_name("lpt\u00b9.x") == "lpt\u00b9_.x"
    assert export.file_name("Tab\there") == "Tab_here"


def test_a_camera_whose_list_names_no_piece_has_no_video(tmp_path: Path) -> None:
    folder = tmp_path / "cam1"
    folder.mkdir()
    (folder / "odd.mkv").write_bytes(b"x")
    (folder / "segments.txt").write_text("odd\n")
    assert not export.has_video(folder)


def test_the_cameras_are_exported_in_turn_their_progress_told_as_a_share(
    tmp_path: Path,
) -> None:
    record(tmp_path / "cam1", START, 40)
    record(tmp_path / "cam2", START, 40)
    jobs = [(tmp_path / c, tmp_path / f"{c}.mp4") for c in ("cam1", "cam2")]
    shares: list[int] = []
    written, error, skipped = export.export_all(jobs, shares.append)
    assert (written, error, skipped) == (
        [tmp_path / "cam1.mp4", tmp_path / "cam2.mp4"],
        "",
        0,
    )
    assert shares == sorted(shares) and shares[-1] == export.STEPS


def test_a_camera_that_fails_is_told_the_next_exported_and_a_stop_ends_them_all(
    tmp_path: Path,
) -> None:
    record(tmp_path / "cam2", START, 40)
    jobs = [
        (tmp_path / "cam2", tmp_path / "missing" / "Main.mp4"),  # no such folder
        (tmp_path / "cam2", tmp_path / "Tele.mp4"),
    ]
    written, error, _ = export.export_all(jobs)
    assert written == [tmp_path / "Tele.mp4"]
    assert error.startswith("Main: ")
    stopped = export.export_all(jobs[1:], cancelled=lambda: True)
    assert stopped == ([], export.CANCELLED, 0)


def test_each_camera_goes_up_to_the_last_piece_closed_as_the_export_began(
    tmp_path: Path,
) -> None:
    record(tmp_path / "cam1", START, 40)
    record(tmp_path / "cam2", START, 40)
    jobs = [(tmp_path / c, tmp_path / f"{c}.mp4") for c in ("cam1", "cam2")]
    more = {"to": True}

    def recording(_share: int) -> None:  # cam2 records on while cam1 is exported
        if more.pop("to", False):
            record(tmp_path / "cam2", START + 60_000, 40)

    written, _, _ = export.export_all(jobs, recording)
    assert read(written[1])[1] == [k * 33 for k in range(40)]  # not the minute after


def track_beep(path: Path) -> tuple[float, int]:
    """Where the beep is in an exported file's sound, seconds from its start, and the
    file's sound streams."""
    with av.open(str(path)) as container:
        if not container.streams.audio:
            return -1.0, 0
        audio = container.streams.audio[0]
        samples = np.concatenate(
            [frame.to_ndarray()[0] for frame in container.decode(audio)]
        )
        start = float(audio.start_time * audio.time_base) if audio.start_time else 0.0
        loud = np.flatnonzero(np.abs(samples) > 0.1)
        return start + loud[0] / audio.sample_rate, len(container.streams.audio)


def test_an_exported_file_has_its_sound_in_step_with_the_picture(
    tmp_path: Path,
) -> None:
    # specs/013: the beep 1.5 s into the recording, heard 1.5 s into the file.
    recorded(tmp_path)
    (written,) = export.export(tmp_path / "cam1", tmp_path / "Main.mp4")
    beep, streams = track_beep(written)
    assert streams == 1
    assert beep == pytest.approx(1.5, abs=0.03)


def test_a_piece_held_a_moment_as_the_export_begins_keeps_its_sound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Its times held by their writer as the sound's pieces are listed: read again, as
    # the window's polls would, never its sound -- the beep -- left out.
    recorded(tmp_path)
    real = video_index.read_times
    held: set[Path] = set()

    def read_times(path: Path) -> Any:
        if path.stem.endswith("-0002") and path not in held:
            held.add(path)
            return None
        return real(path)

    monkeypatch.setattr(video_index, "read_times", read_times)
    (written,) = export.export(tmp_path / "cam1", tmp_path / "Main.mp4")
    assert held
    assert track_beep(written)[0] == pytest.approx(1.5, abs=0.03)


def test_a_piece_whose_times_never_read_holds_an_export_a_moment_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Times a crash garbled are read no better later: half a second, not seconds,
    # each export of the camera waits for them.
    recorded(tmp_path)
    (next(iter(sorted((tmp_path / "cam1").glob("*-0002.times"))))).write_text("x\n")
    waited: list[float] = []
    monkeypatch.setattr(export.time, "sleep", waited.append)
    export.export(tmp_path / "cam1", tmp_path / "Main.mp4")
    assert sum(waited) <= 0.5


def test_a_lens_without_sound_is_exported_with_its_phones(tmp_path: Path) -> None:
    recorded(tmp_path)
    record(tmp_path / "cam2", HEARD, 60)  # the telephoto, frames alone, beside it
    (alone,) = export.export(tmp_path / "cam2", tmp_path / "Tele.mp4")
    assert track_beep(alone)[1] == 0  # no sound of its own
    written, error, _ = export.export_all(
        [(tmp_path / "cam2", tmp_path / "Tele2.mp4")],
        sounds={tmp_path / "cam2": [(tmp_path / "cam1", 0)]},
    )
    assert error == ""
    beep, streams = track_beep(written[0])
    assert streams == 1
    assert beep == pytest.approx(1.5, abs=0.03)
    # The main lens aligned 200 ms later than the telephoto on an event: its sound
    # goes that much later in the telephoto's file, as it plays.
    later, _, _ = export.export_all(
        [(tmp_path / "cam2", tmp_path / "Tele3.mp4")],
        sounds={tmp_path / "cam2": [(tmp_path / "cam1", 200)]},
    )
    assert track_beep(later[0])[0] == pytest.approx(1.7, abs=0.03)


def test_a_phones_lenses_exported_together_list_its_sound_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A day of the main lens's times read once, not once for each of its phone's.
    recorded(tmp_path)
    record(tmp_path / "cam2", HEARD, 60)
    record(tmp_path / "cam3", HEARD, 60)
    real = export._listed
    listed: list[Path] = []

    def counted(folder: Path, cancelled: Any) -> Any:
        listed.append(folder)
        return real(folder, cancelled)

    monkeypatch.setattr(export, "_listed", counted)
    main = [(tmp_path / "cam1", 0)]
    written, error, _ = export.export_all(
        [(tmp_path / f"cam{n}", tmp_path / f"Lens{n}.mp4") for n in (1, 2, 3)],
        sounds={tmp_path / "cam2": main, tmp_path / "cam3": main},
    )
    assert error == ""
    assert all(track_beep(path)[1] == 1 for path in written)
    assert listed == [tmp_path / "cam1"]


def test_a_lens_is_exported_with_its_phones_sound_whichever_lens_kept_it_then(
    tmp_path: Path,
) -> None:
    # The main lens left out a while, the telephoto took the microphone: each lens's
    # file has the phone's sound throughout, as the window plays it.
    recorded(tmp_path)  # the main lens's sound, 0-3 s, its beep at 1.5 s
    (tmp_path / "late").mkdir()
    record(tmp_path / "cam2", HEARD, 90)  # the telephoto's frames, 0-3 s alone
    recorded(tmp_path / "late", 3, folder=tmp_path / "cam2", start=HEARD + 3000)
    both = [(tmp_path / "cam2", 0), (tmp_path / "cam1", 0)]
    written, error, _ = export.export_all(
        [(tmp_path / "cam2", tmp_path / "Tele.mp4")], sounds={tmp_path / "cam2": both}
    )
    assert error == ""
    first, second = written  # the format changed at 3 s: a file of its own on
    assert track_beep(first)[0] == pytest.approx(1.5, abs=0.03)  # the main lens's
    assert track_beep(second)[0] == pytest.approx(1.5, abs=0.03)  # the telephoto's


def test_a_camera_without_sound_is_exported_without_looking_for_it_piece_by_piece(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hours of pieces are not opened again for a sound none of them keeps (013).
    record(tmp_path / "cam1", START, 70)

    def looked(*_: object) -> object:
        raise AssertionError("looked for sound piece by piece")

    monkeypatch.setattr(export.sound, "pieces", looked)
    (written,) = export.export(tmp_path / "cam1", tmp_path / "Side.mp4")
    assert read(written)[1]  # its frames all the same


def test_a_files_sound_holds_one_form_of_it_another_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A streaming app connecting again in stereo: one track holds one form of sound.
    recorded(tmp_path)
    real = export.sound.pieces

    def two_forms(index: Any, from_ms: int, **_: Any) -> Any:
        for n, piece in enumerate(real(index, from_ms, **_)):
            if n >= 60:  # the rest in another form
                piece = export.sound.Piece(
                    piece.ms,
                    piece.end_ms,
                    piece.packet,
                    export.sound.Form("aac", b"\x11\x90", 48000, "stereo"),
                    piece.path,
                )
            yield piece

    monkeypatch.setattr(export.sound, "pieces", two_forms)
    (written,) = export.export(tmp_path / "cam1", tmp_path / "Main.mp4")
    with av.open(str(written)) as container:
        heard = [p for p in container.demux(container.streams.audio[0]) if p.size]
    assert len(heard) == 60


def test_a_piece_before_a_files_first_frame_chooses_no_form_for_its_sound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The piece the sound begins on, a moment before the file's first frame, of the
    # form before a streaming app connected again: the track takes the file's own.
    recorded(tmp_path)
    real = export.sound.pieces

    def preroll(index: Any, from_ms: int, **kwargs: Any) -> Any:
        found = real(index, from_ms, **kwargs)
        first = next(found)
        stereo = export.sound.Form("aac", b"\x11\x90", 48000, "stereo")
        yield export.sound.Piece(
            from_ms - 30, from_ms - 9, first.packet, stereo, first.path
        )
        yield first
        yield from found

    monkeypatch.setattr(export.sound, "pieces", preroll)
    (written,) = export.export(tmp_path / "cam1", tmp_path / "Main.mp4")
    with av.open(str(written)) as container:
        heard = [p for p in container.demux(container.streams.audio[0]) if p.size]
    assert len(heard) > 100  # its 3 s, never passed over as another form


def test_a_sound_that_fails_as_a_file_begins_leaves_no_part_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Its first pieces failing to be read: the file half begun is gone, its name free.
    recorded(tmp_path)

    def failing(*_: Any, **__: Any) -> Any:
        raise KeyboardInterrupt  # a failure no reader catches

        yield  # pragma: no cover - a generator, as the pieces are

    monkeypatch.setattr(export.sound, "pieces", failing)
    with pytest.raises(KeyboardInterrupt):
        export.export(tmp_path / "cam1", tmp_path / "Main.mp4")
    assert not list(tmp_path.glob("*.part"))


def test_a_gap_in_an_exported_files_sound_is_silence_so_it_stays_in_step(
    tmp_path: Path,
) -> None:
    # A player plays a file's sound piece after piece: a gap left as a jump of time
    # would put what comes after it early by the gap's length (specs/013).
    recorded(tmp_path, gap=(500, 1000))
    (written,) = export.export(tmp_path / "cam1", tmp_path / "Main.mp4")
    beep, _ = track_beep(written)  # its samples counted one after another
    assert beep == pytest.approx(1.5, abs=0.03)


def test_a_sound_mp4_will_not_take_costs_the_sound_never_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded(tmp_path)

    def refused(*_: object) -> object:
        raise av.FFmpegError(22, "refused")

    monkeypatch.setattr(export._Out, "_sound_stream", refused)
    (written,) = export.export(tmp_path / "cam1", tmp_path / "Main.mp4")
    assert track_beep(written)[1] == 0
    assert read(written)[1]  # its frames all the same


def test_a_sound_heard_in_the_middle_of_a_race_alone_is_exported(
    tmp_path: Path,
) -> None:
    # The microphone allowed after the start and refused again before the end.
    record(tmp_path / "cam1", HEARD - 20_000, 300)  # frames alone before
    recorded(tmp_path)  # the sound's 3 s
    record(tmp_path / "cam1", HEARD + 20_000, 300)  # frames alone after
    assert export.has_sound(tmp_path / "cam1")


def test_a_cameras_newest_pieces_are_always_looked_into_for_sound(
    tmp_path: Path,
) -> None:
    # The microphone allowed late: 14 pieces without, then 3 with -- the newest.
    record(tmp_path / "cam1", HEARD - 20_000, 14 * 30)
    recorded(tmp_path)
    assert len(export.pieces(tmp_path / "cam1")) == 17
    assert export.has_sound(tmp_path / "cam1")
