"""The sound played with the picture, through Qt's audio output (specs/013-sound)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.widgets import sound as player
from tests.conftest import wait_until
from tests.test_sound import RATE, START, beep_at, recorded


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

    def stop(self) -> None:
        self.stopped = True


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
    silent.play(index, START, 1.0)
    assert not silent.playing


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


def test_the_sound_says_it_has_ended_once_all_of_it_is_given(tmp_path: Path) -> None:
    index = recorded(tmp_path)
    output = Output()
    played = player.SoundPlayer(
        output=lambda: (output, player.RATE, player.CHANNELS), clock=still
    )
    assert not played.ended  # nothing played: nothing ended
    played.play(index, START + 2500, 1.0)
    wait_until(lambda: played.ended)  # the half second left, given whole
    assert len(output.taken) == pytest.approx(4 * RATE * 0.5, rel=0.2)
    played.stop()
    assert not played.ended


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
    played.play(index, START, 1.0)
    now[0] += 1.0
    wait_until(lambda: played.ended)
    assert beep_at(heard(output)) == pytest.approx(0.5, abs=0.05)  # 1.5 s in, less 1
    played.stop()
