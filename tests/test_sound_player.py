"""The sound played with the picture, through Qt's audio output (specs/013-sound)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.widgets import sound as player
from tests.conftest import wait_until
from tests.test_sound import RATE, START, beep_at, recorded


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
    played = player.SoundPlayer(output=lambda rate, channels: output)
    played.play(index, START + 500, rate)
    assert played.playing
    wait_until(lambda: len(output.taken) > 4 * RATE * (2.0 / rate))  # past the beep
    # What is heard lags what is written by the output's buffer: skipped.
    expected = (1.0 - player.BUFFER_S * rate) / rate
    assert beep_at(heard(output)) == pytest.approx(expected, abs=0.05 / rate)
    played.stop()
    assert output.stopped
    assert not played.playing


def test_stopped_it_gives_no_more_and_without_an_output_it_plays_none(
    tmp_path: Path,
) -> None:
    index = recorded(tmp_path)
    output = Output()
    output.free = 4 * 4800  # a tenth of a second at a time
    played = player.SoundPlayer(output=lambda rate, channels: output)
    played.play(index, START, 1.0)
    wait_until(lambda: len(output.taken) > 0)
    played.stop()
    taken = len(output.taken)
    output.free = 10**8
    played._pump()  # a tick already on its way
    assert len(output.taken) == taken
    silent = player.SoundPlayer(output=lambda rate, channels: None)
    silent.play(index, START, 1.0)
    assert not silent.playing


def test_qts_output_is_made_or_none_without_a_device() -> None:
    made = player.default_output(player.RATE, player.CHANNELS)
    assert made is None or hasattr(made, "bytesFree")  # CI's machine has no device
