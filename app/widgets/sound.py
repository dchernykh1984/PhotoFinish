"""The sound played with the picture (specs/013-sound).

A camera's sound from the moment playing goes on from, at its rate, is rendered on a
thread of its own (app/sound.py) and fed to Qt's audio output as it plays: its first
sample is the moment asked, heard the output's own latency on -- its buffer fills
behind that sample, it never delays it --, so what is heard is what the picture
shows. A computer with no audio output plays none.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer

from app import sound
from app.video_index import VideoIndex

RATE = 48000
CHANNELS = 2
BUFFER_S = 0.15  # the output's own: room for the window's thread to be late a while
AHEAD_S = 0.5  # rendered ahead of what the output has taken
PUMP_MS = 10
# FFmpeg's layout for a device's channels: one it prefers past these is not played.
LAYOUTS = {1: "mono", 2: "stereo", 3: "2.1", 4: "quad", 5: "5.0", 6: "5.1", 8: "7.1"}


def default_output() -> tuple[Any, int, int] | None:
    """Qt's audio output, 16-bit, with its rate and channels: 48 kHz stereo, else
    the rate and channels the device prefers -- a sound card that takes no other --;
    None without one."""
    try:
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
    except ImportError:  # pragma: no cover - a Qt without multimedia
        return None
    device = QMediaDevices.defaultAudioOutput()
    if device.isNull():
        return None
    preferred = device.preferredFormat()
    for rate, channels in (
        (RATE, CHANNELS),
        (preferred.sampleRate(), preferred.channelCount()),
    ):
        form = QAudioFormat()
        form.setSampleRate(rate)
        form.setChannelCount(channels)
        form.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if rate > 0 and channels in LAYOUTS and device.isFormatSupported(form):
            output = QAudioSink(device, form)
            output.setBufferSize(round(BUFFER_S * rate) * channels * 2)
            return output, rate, channels
    return None


class SoundPlayer(QObject):
    """Plays a camera's sound from a moment at a rate until stopped; ``output`` makes
    the output -- Qt's, or a test's --, ``clock`` tells the time it took to start."""

    def __init__(
        self,
        parent: QObject | None = None,
        output: Callable[[], tuple[Any, int, int] | None] = default_output,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._make, self._clock = output, clock
        self._output: Any = None
        self._device: Any = None
        self._chunks: deque[bytes] = deque()
        self._held = 0  # bytes rendered and not yet given to the output
        self._ahead = 0  # bytes rendered ahead at most, at the output's rate
        self._frame = 4  # bytes a sample of every channel takes at the output
        self._asked: float | None = None  # when play was asked, until the first write
        self._out_rate = RATE
        self._lock = threading.Lock()
        self._room = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._rendered = False  # the rendering has given all the sound there is
        self._timer = QTimer(self)
        self._timer.setInterval(PUMP_MS)
        self._timer.timeout.connect(self._pump)

    @property
    def playing(self) -> bool:
        return self._thread is not None

    @property
    def ended(self) -> bool:
        """All the sound there was has been given: a recording that grew since may
        have more, for the window to play on."""
        with self._lock:
            return self.playing and self._rendered and not self._chunks

    def play(self, index: VideoIndex, from_ms: int, rate: float) -> None:
        """The camera's sound from ``from_ms`` on its own times, at ``rate``; what
        was playing stopped first. Nothing without an output."""
        self.stop()
        made = self._make()
        if made is None:
            return
        self._output, out_rate, channels = made
        self._device = self._output.start()
        if self._device is None:
            self.stop()
            return
        self._ahead = round(AHEAD_S * out_rate) * channels * 2
        self._frame, self._out_rate = channels * 2, out_rate
        self._asked = self._clock()
        layout = LAYOUTS.get(channels, "stereo")
        renderer = sound.Renderer(
            sound.pieces(index, from_ms), from_ms, rate, out_rate, layout
        )
        stopped = self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._render, args=(renderer, stopped), daemon=True
        )
        self._thread.start()
        self._timer.start()

    def stop(self) -> None:
        """Silent from now on: the rendering told to end, the output stopped."""
        self._timer.stop()
        with self._lock:
            self._stopped.set()
            self._chunks.clear()
            self._held = 0
            self._rendered = False
            self._room.notify_all()
        self._thread = None  # a daemon: it ends at its next piece, waited for by none
        if self._output is not None:
            self._output.stop()
        self._output = self._device = None

    def _render(self, renderer: sound.Renderer, stopped: threading.Event) -> None:
        """The sound rendered ahead of the output by AHEAD_S at most, until stopped
        or ended; a recording that cannot be read ends it."""
        ahead = self._ahead
        try:
            while not stopped.is_set():
                chunk = renderer.read()
                if not chunk:
                    with self._lock:
                        self._rendered = not stopped.is_set()
                    return
                with self._lock:
                    while self._held > ahead and not stopped.is_set():
                        self._room.wait(0.1)
                    if stopped.is_set():
                        return
                    self._chunks.append(chunk)
                    self._held += len(chunk)
        except Exception:
            return

    def _pump(self) -> None:
        """What the output has room for, given it; the first time, the time since
        play was asked left out of it -- the sound made, opened and decoded while the
        picture played on --, so it keeps up with the picture."""
        if self._output is None or self._device is None:
            return
        with self._lock:
            if self._asked is not None and self._chunks:
                late = self._clock() - self._asked
                self._asked = None
                self._skip(round(late * self._out_rate) * self._frame)
            room = int(self._output.bytesFree())
            while self._chunks and room > 0:
                chunk = self._chunks.popleft()
                taken = int(self._device.write(chunk[:room]))
                if taken < len(chunk):
                    self._chunks.appendleft(chunk[max(taken, 0) :])
                taken = max(taken, 0)
                self._held -= taken
                room -= taken
                if not taken:
                    break
            self._room.notify_all()

    def _skip(self, count: int) -> None:
        """``count`` bytes of what was rendered left out; the lock held."""
        while count > 0 and self._chunks:
            chunk = self._chunks.popleft()
            if len(chunk) > count:
                self._chunks.appendleft(chunk[count:])
            taken = min(count, len(chunk))
            self._held -= taken
            count -= taken
