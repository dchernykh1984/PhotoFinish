"""A camera's sound from a moment, as it is played (specs/013-sound)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import av
import numpy as np
import pytest

from app import sound
from app.recorder.segments import SegmentWriter, fraction, in_ms
from app.recorder.testcam import render
from app.video_index import VideoIndex
from tests.test_segments import START

RATE = 48000
BEEP_MS = 1500  # into the recording
TONE = 1000  # Hz


def beeping(path: Path, seconds: int) -> None:
    """A phone's stream, H.264 and AAC mono at 48 kHz: silence but for a 1 kHz beep
    of 100 ms at BEEP_MS."""
    with av.open(str(path), "w", format="matroska") as out:
        video = out.add_stream("libx264", rate=30, options={"g": "30", "bf": "0"})
        video.width, video.height, video.pix_fmt = 160, 96, "yuv420p"
        audio = out.add_stream("aac", rate=RATE)
        audio.layout = "mono"
        heard = 0
        for k in range(30 * seconds):
            frame = av.VideoFrame.from_ndarray(render(START + k * 33, 160, 96))
            frame.pts = k
            for packet in video.encode(frame):
                out.mux(packet)
            while heard * 1024 * 1000 < (k + 1) * 33 * RATE:
                at = (np.arange(1024) + heard * 1024) / RATE
                on = (at >= BEEP_MS / 1000) & (at < BEEP_MS / 1000 + 0.1)
                tone = np.where(on, 0.5 * np.sin(2 * np.pi * TONE * at), 0.0)
                piece = av.AudioFrame.from_ndarray(
                    tone.astype(np.float32)[None], format="fltp", layout="mono"
                )
                piece.sample_rate, piece.pts = RATE, heard * 1024
                for packet in audio.encode(piece):
                    out.mux(packet)
                heard += 1
        for stream in (video, audio):
            for packet in stream.encode(None):
                out.mux(packet)


def recorded(
    tmp_path: Path,
    seconds: int = 3,
    again: int = 0,
    gap: tuple[int, int] | None = None,
    folder: Path | None = None,
) -> VideoIndex:
    """The beeping stream recorded at its own moments from START into ``folder``,
    ``again`` pieces of sound sent twice, none heard within ``gap`` (ms into it)."""
    beeping(tmp_path / "phone.mkv", seconds)
    folder = folder or tmp_path / "cam1"
    writer = SegmentWriter(folder, fps=30)
    with av.open(str(tmp_path / "phone.mkv")) as container:
        sent: list[tuple[av.Packet, int]] = []
        for packet in container.demux():
            if packet.pts is None:
                continue
            into = in_ms(packet.pts, fraction(packet.time_base))
            if packet.stream.type == "video":
                writer.write_packet(packet, START + into)
            elif gap is None or not gap[0] <= into < gap[1]:
                writer.write_audio(packet, START + into)
                sent.append((packet, START + into))
                for old, ms in sent[-again - 1 : -1] if again and into > 2000 else []:
                    writer.write_audio(old, ms)  # sent again, out of order: once
    writer.close()
    index = VideoIndex(folder)
    index.refresh()
    return index


def played(index: VideoIndex, from_ms: int, rate: float = 1.0) -> np.ndarray:
    """What the renderer gives from ``from_ms`` at ``rate``: one channel of it."""
    renderer = sound.Renderer(sound.pieces(index, from_ms), from_ms, rate)
    out = b""
    while chunk := renderer.read():
        out += chunk
    return np.frombuffer(out, np.int16).reshape(-1, 2)[:, 0]


def beep_at(samples: np.ndarray) -> float:
    """Where the beep begins, seconds into the samples."""
    loud = np.flatnonzero(np.abs(samples) > 3000)
    assert loud.size, "no beep heard"
    return float(loud[0] / RATE)


def pitch(samples: np.ndarray) -> float:
    """The beep's frequency, from its zero crossings."""
    loud = np.flatnonzero(np.abs(samples) > 3000)
    beep = samples[loud[0] : loud[-1]].astype(np.int32)
    crossings = np.count_nonzero(np.diff(np.signbit(beep)))
    return crossings / 2 / (beep.size / RATE)


def test_the_sound_from_a_moment_has_the_beep_where_it_was_heard(
    tmp_path: Path,
) -> None:
    index = recorded(tmp_path)
    samples = played(index, START + 500)
    assert beep_at(samples) == pytest.approx(1.0, abs=0.03)
    from_first = played(index, START)  # a decoder gives nothing for its first piece
    assert beep_at(from_first) == pytest.approx(1.5, abs=0.005)
    assert samples.size / RATE == pytest.approx(2.5, abs=0.1)  # to the recording's end


@pytest.mark.parametrize("rate", [0.25, 0.5, 2.0, 4.0])
def test_a_rate_stretches_the_time_and_keeps_the_pitch(
    tmp_path: Path, rate: float
) -> None:
    index = recorded(tmp_path)
    samples = played(index, START + 500, rate)
    # On the recording's time: atempo's windows put a sound up to 40 ms early.
    assert beep_at(samples) * rate == pytest.approx(1.0, abs=0.05)
    assert pitch(samples) == pytest.approx(TONE, rel=0.1)


def test_at_x16_the_sound_plays_a_sixteenth_as_long(tmp_path: Path) -> None:
    index = recorded(tmp_path)
    samples = played(index, START, 16.0)
    assert samples.size / RATE == pytest.approx(3.0 / 16, abs=0.03)


def test_the_pieces_come_in_order_each_once_across_segments(tmp_path: Path) -> None:
    index = recorded(tmp_path, again=15)
    assert len(index.paths) == 3
    found = [piece.ms for piece in sound.pieces(index, START)]
    assert found == sorted(found)
    steps = np.diff(found)
    assert steps.min() >= 20  # none twice
    assert steps.max() <= 22  # none lost at a segment's end
    assert found[-1] - found[0] == pytest.approx(3000, abs=60)


def test_a_gap_in_the_sound_is_silence_of_its_length(tmp_path: Path) -> None:
    index = recorded(tmp_path, gap=(500, 1000))
    samples = played(index, START)
    assert beep_at(samples) == pytest.approx(1.5, abs=0.03)  # still where it was


def test_a_segment_keeps_sound_or_not(tmp_path: Path) -> None:
    index = recorded(tmp_path)
    assert all(sound.has_sound(path) for path in index.paths)
    assert not sound.has_sound(tmp_path / "missing.mkv")
    silent = tmp_path / "cam2"
    writer = SegmentWriter(silent, fps=30)
    writer.write(render(START, 160, 96), START)
    writer.close()
    assert not sound.has_sound(next(silent.glob("*-*-*.mkv")))


def test_the_segments_from_a_frame_begin_with_the_one_before_it(
    tmp_path: Path,
) -> None:
    index = recorded(tmp_path)
    first, second, third = index.paths
    assert index.segments_from(0) == [first, second, third]
    middle = index.at_or_before(START + 1500)
    assert middle is not None
    assert index.frame(middle).path == second
    assert index.segments_from(middle) == [first, second, third]
    last = index.at_or_before(START + 2900)
    assert last is not None
    assert index.segments_from(last) == [second, third]
    assert index.at_or_before(START - 10_000) == 0
    assert VideoIndex(tmp_path / "none").segments_from(0) == []


def test_the_segments_are_listed_as_the_pieces_are_asked_for_not_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The window refreshes the index on its thread as the sound is read on another:
    # the segments are listed where pieces() is called, the files read later.
    index = recorded(tmp_path)
    found = sound.pieces(index, START)

    def refreshed(*_: object) -> list[Path]:
        raise AssertionError("the index read on the sound's thread")

    monkeypatch.setattr(index, "segments_from", refreshed)
    monkeypatch.setattr(index, "at_or_before", refreshed)
    assert len(list(found)) > 100


def test_a_long_gap_is_silence_made_a_little_at_a_time(tmp_path: Path) -> None:
    # Two minutes with no sound -- a microphone lost, a recorder down -- is never
    # held whole: silence comes a tenth of a second at a time.
    index = recorded(tmp_path)
    found = list(sound.pieces(index, START))
    half = len(found) // 2
    for piece in found[half:]:
        piece.ms += 120_000
        piece.end_ms += 120_000
    renderer = sound.Renderer(iter(found), START, 1.0)
    sizes: list[int] = []
    while chunk := renderer.read():
        sizes.append(len(chunk))
    assert sum(sizes) / 4 / RATE == pytest.approx(3.0 + 120.0, abs=0.2)
    assert max(sizes) <= 4 * RATE * 0.15


def test_a_phones_other_lenses_are_its_cameras_beside_the_one_shown() -> None:
    main: dict[str, object] = {"id": "cam1", "phone": "p1", "offset_ms": 50}
    tele: dict[str, object] = {"id": "cam2", "phone": "p1", "offset_ms": 20}
    other: dict[str, object] = {"id": "cam3", "phone": "p2"}
    alone: dict[str, object] = {"id": "cam4"}
    cameras = [main, tele, other, alone]
    assert sound.phone_mates(tele, cameras) == [main]
    assert sound.phone_mates(alone, cameras) == []  # no phone: none of its own
    assert sound.shift_ms(tele, main) == 30  # the main lens's sound 30 ms later
    assert sound.shift_ms(main, main) == 0


def test_whose_sound_is_the_cameras_own_else_its_phones_first_that_has_some() -> None:
    main: dict[str, object] = {"id": "cam1", "phone": "p1"}
    tele: dict[str, object] = {"id": "cam2", "phone": "p1"}
    other: dict[str, object] = {"id": "cam3", "phone": "p2"}
    cameras = [main, tele, other]
    has = {"cam1"}
    heard = lambda camera: camera["id"] in has  # noqa: E731
    assert sound.whose(tele, cameras, heard) is main  # its phone's
    assert sound.whose(main, cameras, heard) is main  # its own
    assert sound.whose(other, cameras, heard) is None  # another phone's: none
    has.add("cam2")
    assert sound.whose(tele, cameras, heard) is tele


def test_a_piece_that_cannot_be_decoded_costs_its_own_length_alone(
    tmp_path: Path,
) -> None:
    # A damaged piece -- a segment a crash cut short -- is silence, the rest heard.
    index = recorded(tmp_path)
    found = list(sound.pieces(index, START))
    bad = found[20]
    damaged = av.Packet(b"\xff\xf1" + bytes(range(200)))
    damaged.pts = damaged.dts = bad.packet.pts
    damaged.time_base = bad.packet.time_base
    found[20] = sound.Piece(bad.ms, bad.end_ms, damaged, bad.form, bad.path)
    renderer = sound.Renderer(iter(found), START, 1.0)
    out = b""
    while chunk := renderer.read():
        out += chunk
    samples = np.frombuffer(out, np.int16).reshape(-1, 2)[:, 0]
    assert samples.size / RATE == pytest.approx(3.0, abs=0.1)
    assert beep_at(samples) == pytest.approx(1.5, abs=0.03)


def test_pieces_follow_a_recording_that_grows_until_finished(tmp_path: Path) -> None:
    # Played behind live: the segments closed since are heard on, in order, each once.
    index = recorded(tmp_path)
    first, *later = index.paths
    found = sound.Pieces([first], START, follows=True)
    got: list[int] = []
    reader = threading.Thread(target=lambda: got.extend(p.ms for p in found))
    reader.start()
    time.sleep(0.3)
    assert got and max(got) < START + 1000  # the first second, then waiting
    found.extend(later)
    time.sleep(0.3)
    assert reader.is_alive()  # waiting for more
    found.finish()
    reader.join(timeout=5)
    assert got == sorted(got)
    assert got[-1] - got[0] == pytest.approx(3000, abs=60)


def test_whether_a_segment_has_sound_is_read_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A closed segment never changes: the window opens no file twice for it.
    index = recorded(tmp_path)
    path = index.paths[0]
    assert sound.has_sound(path)
    opened: list[object] = []
    real = av.open

    def counted(*args: Any, **kwargs: Any) -> Any:
        opened.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(sound.av, "open", counted)
    assert sound.has_sound(path)
    assert opened == []
