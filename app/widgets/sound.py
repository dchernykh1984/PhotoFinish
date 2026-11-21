"""The sound played with the picture (specs/013-sound).

A camera's sound from the moment playing goes on from, at its rate, is rendered on a
thread of its own (app/sound.py) and fed to Qt's audio output as it plays. Its
buffer's length is skipped at the start, so what is heard is what the picture shows.
A computer with no audio output plays none.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer

from app import sound
from app.video_index import VideoIndex

RATE = 48000
CHANNELS = 2
BUFFER_S = 0.15  # the output's own: what is heard lags what is written by this much
AHEAD_S = 0.5  # rendered ahead of what the output has taken
PUMP_MS = 10


def default_output(rate: int, channels: int) -> Any:
    """Qt's audio output at ``rate`` and ``channels``, 16-bit; None without one."""
    try:
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
    except ImportError:  # pragma: no cover - a Qt without multimedia
        return None
    device = QMediaDevices.defaultAudioOutput()
    if device.isNull():
        return None
    form = QAudioFormat()
    form.setSampleRate(rate)
    form.setChannelCount(channels)
    form.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    if not device.isFormatSupported(form):
        return None
    output = QAudioSink(device, form)
    output.setBufferSize(round(BUFFER_S * rate) * channels * 2)
    return output


class SoundPlayer(QObject):
    """Plays a camera's sound from a moment at a rate until stopped; ``output`` makes
    the output -- Qt's, or a test's."""

    def __init__(
        self,
        parent: QObject | None = None,
        output: Callable[[int, int], Any] = default_output,
    ) -> None:
        super().__init__(parent)
        self._make = output
        self._output: Any = None
        self._device: Any = None
        self._chunks: deque[bytes] = deque()
        self._held = 0  # bytes rendered and not yet given to the output
        self._lock = threading.Lock()
        self._room = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._timer = QTimer(self)
        self._timer.setInterval(PUMP_MS)
        self._timer.timeout.connect(self._pump)

    @property
    def playing(self) -> bool:
        return self._thread is not None

    def play(self, index: VideoIndex, from_ms: int, rate: float) -> None:
        """The camera's sound from ``from_ms`` on its own times, at ``rate``; what
        was playing stopped first. Nothing without an output."""
        self.stop()
        self._output = self._make(RATE, CHANNELS)
        if self._output is None:
            return
        self._device = self._output.start()
        if self._device is None:
            self.stop()
            return
        skipped = round(from_ms + BUFFER_S * rate * 1000)  # heard as the picture shows
        renderer = sound.Renderer(
            sound.pieces(index, skipped), skipped, rate, RATE, "stereo"
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
            self._room.notify_all()
        self._thread = None  # a daemon: it ends at its next piece, waited for by none
        if self._output is not None:
            self._output.stop()
        self._output = self._device = None

    def _render(self, renderer: sound.Renderer, stopped: threading.Event) -> None:
        """The sound rendered ahead of the output by AHEAD_S at most, until stopped
        or ended; a recording that cannot be read ends it."""
        ahead = round(AHEAD_S * RATE) * CHANNELS * 2
        try:
            while not stopped.is_set():
                chunk = renderer.read()
                if not chunk:
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
        """What the output has room for, given it."""
        if self._output is None or self._device is None:
            return
        with self._lock:
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
