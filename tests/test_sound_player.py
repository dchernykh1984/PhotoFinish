"""The sound played with the picture, through Qt's audio output (specs/013-sound)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app import video_index
from app.recorder.segments import SegmentWriter, fraction, in_ms
from app.video_index import VideoIndex
from app.widgets import sound as player
from tests.conftest import wait_until
from tests.test_sound import RATE, START, beep_at, beeping, recorded


def still() -> float:
    """A clock that stands: the sound started at once."""
    return 100.0


class Output:
    """Stands for Qt's audio output: takes what it has room for."""

    def __init__(self) -> None:
        self.taken = bytearray()
        self.free = 10**8
        self.stopped = False

    def start(self) -> Output:
        return self

    def write(self, data: bytes) -> int:
        took = data[: self.free]
        self.taken += took
        return len(took)

    def bytesFree(self) -> int:  # noqa: N802 - Qt's name
        return self.free

    def bufferSize(self) -> int:  # noqa: N802 - Qt's name
        return self.free

    def stop(self) -> None:
        self.stopped = True


def given(played: player.SoundPlayer) -> bool:
    """All its sound rendered and given to the output: its thread ended."""
    thread = played._thread
    return thread is not None and not thread.is_alive() and not played._chunks


def heard(output: Output) -> np.ndarray:
    return np.frombuffer(bytes(output.taken), np.int16).reshape(-1, 2)[:, 0]


@pytest.mark.parametrize("rate", [1.0, 2.0])
def test_the_sound_plays_from_the_moment_its_buffer_ahead(
    tmp_path: Path, rate: float
) -> None:
    index = recorded(tmp_path)
    output = Output()
    played = player.SoundPlayer(
        output=lambda: (output, player.RATE, player.CHANNELS), clock=still
    )
    played.play(index, START + 500, rate)
    assert played.playing
    wait_until(lambda: len(output.taken) > 4 * RATE * (2.0 / rate))  # past the beep
    # The first sample written is the moment asked: heard as the output's own small
    # latency on, its buffer filling behind it -- what is heard is what is shown.
    assert beep_at(heard(output)) == pytest.approx(1.0 / rate, abs=0.05 / rate)
    played.stop()
    assert output.stopped
    assert not played.playing


def test_stopped_it_gives_no_more_and_without_an_output_it_plays_none(
    tmp_path: Path,
) -> None:
    index = recorded(tmp_path)
    output = Output()
    output.free = 4 * 4800  # a tenth of a second at a time
    played = player.SoundPlayer(
        output=lambda: (output, player.RATE, player.CHANNELS), clock=still
    )
    played.play(index, START, 1.0)
    wait_until(lambda: len(output.taken) > 0)
    played.stop()
    taken = len(output.taken)
    output.free = 10**8
    played._pump()  # a tick already on its way
    assert len(output.taken) == taken
    silent = player.SoundPlayer(output=lambda: None)
    said: list[str] = []
    silent.failed.connect(said.append)
    silent.play(index, START, 1.0)
    silent.play(index, START, 2.0)  # each play, speed and gap: said once
    assert not silent.playing
    refusing = Output()
    refusing.start = lambda: None  # type: ignore[method-assign,assignment,return-value]
    silent._make = lambda: (refusing, player.RATE, player.CHANNELS)
    silent.play(index, START, 1.0)
    assert not silent.playing
    assert said == [
        "The sound cannot be played: no audio output",
        "The sound cannot be played: the audio output would not start",
    ]


def test_qts_output_is_made_or_none_without_a_device() -> None:
    made = player.default_output()
    assert made is None or hasattr(made[0], "bytesFree")  # CI's machine has no device


def test_an_output_that_takes_another_rate_and_channels_is_played_in_them(
    tmp_path: Path,
) -> None:
    # A sound card that will not take 48 kHz stereo: what it prefers.
    index = recorded(tmp_path)
    output = Output()
    played = player.SoundPlayer(output=lambda: (output, 44100, 1), clock=still)
    played.play(index, START + 500, 1.0)
    wait_until(lambda: len(output.taken) > 2 * 44100 * 2.0)
    samples = np.frombuffer(bytes(output.taken), np.int16)  # one channel
    loud = np.flatnonzero(np.abs(samples) > 3000)
    assert loud[0] / 44100 == pytest.approx(1.0, abs=0.05)
    played.stop()


def test_the_time_the_sound_took_to_start_is_skipped_so_it_keeps_up(
    tmp_path: Path,
) -> None:
    # Made, opened and decoded while the picture played on: what that time held of
    # the sound is not heard late, but left out.
    index = recorded(tmp_path)
    output = Output()
    now = [100.0]
    made = (output, player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=lambda: now[0])
    played.play(index, START + 500, 1.0)
    now[0] += 0.3  # the window busy that long before it gave the output anything
    wait_until(lambda: len(output.taken) > 4 * RATE * 1.5)
    assert beep_at(heard(output)) == pytest.approx(0.7, abs=0.05)
    played.stop()


def test_a_start_longer_than_the_sound_rendered_ahead_is_left_out_whole(
    tmp_path: Path,
) -> None:
    # A second's start, more than the half second rendered ahead: all of it skipped.
    index = recorded(tmp_path)
    output = Output()
    now = [100.0]
    made = (output, player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=lambda: now[0])
    played.play(index, START, 1.0, follows=False)
    now[0] += 1.0
    wait_until(lambda: given(played))
    assert beep_at(heard(output)) == pytest.approx(0.5, abs=0.05)  # 1.5 s in, less 1
    played.stop()


def test_a_sound_that_cannot_be_rendered_ends_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = recorded(tmp_path)

    def broken(_: object) -> bytes:
        raise ValueError("a layout the filters refuse")

    monkeypatch.setattr(player.sound.Renderer, "read", broken)
    made = (Output(), player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=still)
    said: list[str] = []
    played.failed.connect(said.append)
    played.play(index, START, 1.0)
    wait_until(lambda: given(played) and bool(said))  # its thread ended, unraised
    played.play(index, START, 2.0)  # a speed changed, a gap jumped: said once
    wait_until(lambda: given(played))
    QApplication.processEvents()
    assert said == ["The sound cannot be played: a layout the filters refuse"]
    played.stop()


def test_a_sound_replaced_says_nothing_of_its_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Stopped -- the speed changed, a gap jumped -- as it failed: the sound playing
    # now plays on, said to fail by none.
    index = recorded(tmp_path)
    failing = threading.Event()

    def broken(_: object) -> bytes:
        failing.wait(5)
        raise ValueError("a segment read as it was replaced")

    monkeypatch.setattr(player.sound.Renderer, "read", broken)
    made = (Output(), player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=still)
    said: list[str] = []
    played.failed.connect(said.append)
    played.play(index, START, 1.0)
    thread = played._thread
    assert thread is not None
    played.stop()
    failing.set()
    thread.join(5)
    QApplication.processEvents()
    assert said == []


def test_the_time_an_output_takes_to_open_is_left_out_too(tmp_path: Path) -> None:
    index = recorded(tmp_path)
    output = Output()
    now = [100.0]

    def opened() -> tuple[Output, int, int]:
        now[0] += 0.2  # a sound card opening, as macOS and Windows take a while
        return output, player.RATE, player.CHANNELS

    played = player.SoundPlayer(output=opened, clock=lambda: now[0])
    played.play(index, START + 500, 1.0)
    wait_until(lambda: len(output.taken) > 4 * RATE * 1.5)
    assert beep_at(heard(output)) == pytest.approx(0.8, abs=0.05)
    played.stop()


def growing(tmp_path: Path) -> tuple[VideoIndex, Callable[[], None]]:
    """The beeping stream's first second recorded, and what records the rest: a
    recording that grows as it plays."""
    beeping(tmp_path / "phone.mkv", 3)
    folder = tmp_path / "cam1"
    # Open as long as the writing lasts: a segment takes its streams from it.
    container = av.open(str(tmp_path / "phone.mkv"))
    packets = [p for p in container.demux() if p.pts is not None]
    kinds: list[str] = [p.stream.type for p in packets]

    def write(part: list[tuple[av.Packet, str]]) -> None:
        writer = SegmentWriter(folder, fps=30)
        for packet, kind in part:
            ms = START + in_ms(packet.pts or 0, fraction(packet.time_base))
            if kind == "video":
                writer.write_packet(packet, ms)
            else:
                writer.write_audio(packet, ms)
        writer.close()

    both: list[tuple[av.Packet, str]] = list(zip(packets, kinds, strict=True))
    cut = next(
        n
        for n, (p, kind) in enumerate(both)
        if kind == "video" and in_ms(p.pts or 0, fraction(p.time_base)) >= 1000
    )
    write(both[:cut])
    index = VideoIndex(folder)
    index.refresh()

    def grow() -> None:
        write(both[cut:])
        index.refresh()

    return index, grow


def test_the_sound_follows_the_segments_its_recording_gains_as_it_plays(
    tmp_path: Path,
) -> None:
    # Played behind live: the beep in a segment closed after play began is heard.
    index, grow = growing(tmp_path)
    output = Output()
    made = (output, player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=still)
    played.play(index, START, 1.0)
    wait_until(lambda: len(output.taken) > 4 * RATE * 0.7)
    grow()
    played.follow()
    wait_until(lambda: len(output.taken) > 4 * RATE * 2.0)
    assert beep_at(heard(output)) == pytest.approx(1.5, abs=0.03)
    played.stop()


def test_a_recording_not_followed_is_heard_to_its_end(tmp_path: Path) -> None:
    # Its recorder ended: the pieces a next segment's might have come before are
    # heard, none waited for -- the last 200 ms too.
    index = recorded(tmp_path)
    output = Output()
    made = (output, player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=still)
    played.play(index, START, 1.0, follows=False)
    wait_until(lambda: given(played))
    assert len(heard(output)) / RATE > 2.95  # the 3 s recorded, to their end
    played.stop()


def test_a_segment_whose_times_are_held_a_poll_is_heard_in_its_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Followed close behind live: the segment after it listed first. Those after it
    # wait a poll for it, so its sound -- the beep -- is heard, not passed over.
    index, grow = growing(tmp_path)
    real = video_index.read_times
    held: list[Path] = []

    def read_times(path: Path) -> Any:
        if "-0002" in path.stem and not held:
            held.append(path)
            return None
        return real(path)

    monkeypatch.setattr(video_index, "read_times", read_times)
    output = Output()
    made = (output, player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=still)
    played.play(index, START, 1.0)
    grow()  # the third listed, the second's times held
    assert held and index.pending
    played.follow()
    until = time.monotonic() + 1.0
    while time.monotonic() < until:  # the output fed, the rendering on as far as it may
        QApplication.processEvents()
        time.sleep(0.01)
    index.refresh()  # the second read a poll later
    played.follow()
    played.follow(grows=False)
    wait_until(lambda: given(played))
    assert beep_at(heard(output)) == pytest.approx(1.5, abs=0.03)
    played.stop()


def test_a_recording_that_grows_no_more_is_heard_to_its_end(tmp_path: Path) -> None:
    # Its recorder let go and ended as it played: the pieces a next segment's might
    # have come before are heard, none waited for -- the last 200 ms too.
    index, grow = growing(tmp_path)
    output = Output()
    made = (output, player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=still)
    played.play(index, START, 1.0)
    grow()
    played.follow(grows=False)
    wait_until(lambda: given(played))
    assert len(heard(output)) / RATE > 2.95  # the 3 s recorded, to their end
    played.stop()


def test_the_time_the_output_ran_dry_is_left_out_so_the_sound_keeps_up(
    tmp_path: Path,
) -> None:
    # The sound waited 0.4 s for a segment as the picture played on: that much of
    # what came after it is left out.
    index, grow = growing(tmp_path)
    output = Output()
    now = [100.0]
    made = (output, player.RATE, player.CHANNELS)
    played = player.SoundPlayer(output=lambda: made, clock=lambda: now[0])
    played.play(index, START, 1.0)
    wait_until(lambda: len(output.taken) > 4 * RATE * 0.7)
    time.sleep(0.3)
    QApplication.processEvents()
    played._pump()  # dry: the first second given, none left
    now[0] += 0.4
    grow()
    played.follow()
    wait_until(lambda: len(output.taken) > 4 * RATE * 1.8)
    assert beep_at(heard(output)) == pytest.approx(1.5 - 0.4, abs=0.05)
    played.stop()
