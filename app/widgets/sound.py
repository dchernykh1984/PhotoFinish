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

from PySide6.QtCore import QObject, QTimer, Signal

from app import sound
from app.video_index import VideoIndex

RATE = 48000
CHANNELS = 2
BUFFER_S = 0.15  # the output's own: room for the window's thread to be late a while
AHEAD_S = 0.5  # rendered ahead of what the output has taken
PUMP_MS = 10
HELD_POLLS = 2  # polls the segments after one whose times are held wait for it
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

    failed = Signal(str)  # a sound that cannot be played: why, from its thread

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
        self._unskipped = 0  # bytes of that start still to leave out, as they come
        self._out_rate = RATE
        self._buffer = 0
        self._lock = threading.Lock()
        self._room = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._pieces: sound.Pieces | None = None  # what it plays, following its index
        self._index: VideoIndex | None = None
        self._listed = 0  # the index's segments the pieces know of
        self._waited = 0  # polls the newest have waited for one whose times are held
        self._drained: float | None = None  # when the output ran dry, the picture on
        self._said = ""  # the output's failure said last, until one starts
        self._render_said = ""  # a rendering's failure said last, until one renders
        self._timer = QTimer(self)
        self._timer.setInterval(PUMP_MS)
        self._timer.timeout.connect(self._pump)

    @property
    def playing(self) -> bool:
        return self._thread is not None

    def play(
        self, index: VideoIndex, from_ms: int, rate: float, follows: bool = True
    ) -> None:
        """The camera's sound from ``from_ms`` on its own times, at ``rate``; what
        was playing stopped first. Nothing without an output. ``follows``: the
        segments the index gains as it plays are heard on (``follow``)."""
        asked = self._clock()  # the time opening the output takes left out too
        self.stop()
        made = self._make()
        if made is None:
            self._fail("The sound cannot be played: no audio output")
            return
        self._output, out_rate, channels = made
        self._device = self._output.start()
        if self._device is None:
            self.stop()
            self._fail("The sound cannot be played: the audio output would not start")
            return
        self._said = ""  # an output again: a failure after it said again
        self._ahead = round(AHEAD_S * out_rate) * channels * 2
        self._frame, self._out_rate = channels * 2, out_rate
        self._buffer = int(self._output.bufferSize())  # all of it free: run dry
        self._asked = asked
        layout = LAYOUTS.get(channels, "stereo")
        self._pieces = sound.pieces(index, from_ms, follows)
        self._index, self._listed, self._waited = index, len(index.paths), 0
        renderer = sound.Renderer(self._pieces, from_ms, rate, out_rate, layout)
        stopped = self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._render, args=(renderer, stopped), daemon=True
        )
        self._thread.start()
        self._timer.start()

    def _fail(self, why: str) -> None:
        """Said once until an output starts: a computer without sound is not told so
        at every play, speed and gap jumped."""
        if why != self._said:
            self._said = why
            self.failed.emit(why)

    def follow(self, grows: bool = True) -> None:
        """The segments the index has gained since, heard on: on the window's
        thread, which refreshes it. A recording that no longer ``grows`` -- its
        recorder let go and ended -- is heard to its end, no segment waited for."""
        if self._pieces is None or self._index is None:
            return
        # A segment listed, its times held a moment: those closed after it wait for
        # it a poll or two, so it is heard in its place, never passed over after them.
        if grows and self._index.pending and self._waited < HELD_POLLS:
            self._waited += 1
            return
        self._waited = 0
        found = sorted(self._index.paths[self._listed :], key=lambda path: path.name)
        self._listed = len(self._index.paths)
        if found:
            self._pieces.extend(found)
        if not grows:
            self._pieces.finish()

    def stop(self) -> None:
        """Silent from now on: the rendering told to end, the output stopped."""
        self._timer.stop()
        if self._pieces is not None:
            self._pieces.cancel()  # its thread reads no segment on, nor waits for one
        self._pieces, self._index, self._drained = None, None, None
        with self._lock:
            self._stopped.set()
            self._chunks.clear()
            self._held = 0
            self._unskipped = 0
            self._room.notify_all()
        self._thread = None  # a daemon: it ends at its next piece, waited for by none
        if self._output is not None:
            self._output.stop()
        self._output = self._device = None

    def _render(self, renderer: sound.Renderer, stopped: threading.Event) -> None:
        """The sound rendered ahead of the output by AHEAD_S at most, until stopped
        or ended; one that cannot be rendered ends it, ``failed`` saying why."""
        ahead = self._ahead
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
                    self._render_said = ""  # rendered: a failure after it said again
        except Exception as error:  # a sound that cannot be played is not heard
            why = f"The sound cannot be played: {error}"
            # Replaced, the one playing now has not failed; said once, not at each play.
            if not stopped.is_set() and why != self._render_said:
                self._render_said = why
                self.failed.emit(why)

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
                self._unskipped = round(late * self._out_rate) * self._frame
            self._dry()
            # More than was rendered ahead as it started: the rest as it comes.
            self._unskipped = self._skip(self._unskipped)
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

    def _skip(self, count: int) -> int:
        """``count`` bytes of what was rendered left out, the lock held; those not
        rendered yet returned."""
        while count > 0 and self._chunks:
            chunk = self._chunks.popleft()
            if len(chunk) > count:
                self._chunks.appendleft(chunk[count:])
            taken = min(count, len(chunk))
            self._held -= taken
            count -= taken
        return count

    def _dry(self) -> None:
        """The output run dry -- the sound waited for segments, the window busy --
        while the picture played on: as much left out once the sound comes again,
        so it keeps up with the picture. The lock held."""
        if self._asked is not None or self._output is None:
            return  # not begun
        if not self._chunks:
            # Empty, or as good as: an output's free room may stop a period short.
            # Dry once what it still holds has played: never counted as silence.
            queued = self._buffer - int(self._output.bytesFree())
            if self._drained is None and queued <= self._buffer // 8:
                held = max(queued, 0) / (self._out_rate * self._frame)
                self._drained = self._clock() + held
            return
        if self._drained is not None:
            late = max(self._clock() - self._drained, 0.0)
            self._drained = None
            self._unskipped += round(late * self._out_rate) * self._frame
