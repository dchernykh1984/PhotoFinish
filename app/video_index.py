"""A camera's recorded frames: closed segments, frame times and gaps.

The window refreshes a camera's index as it polls: segments closed since -- the new
names in the recorder's ``segments.txt`` -- are read from their ``.times`` and
appended. Frame times are kept in numpy arrays in time
order, so the frame nearest a moment is a binary search, and a frame is named by
its place in that order. Gaps come from ``gaps.txt``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from app.files import Appended
from app.recorder.segments import SEGMENTS

TRIES = 20  # polls a listed segment's times are read again before it is given up


@dataclass(frozen=True)
class Frame:
    """A recorded frame: its segment, its timestamp there, its moment (Unix ms)."""

    path: Path
    pts: int
    ms: int


@dataclass(frozen=True)
class Gap:
    start_ms: int
    end_ms: int
    reason: str


class VideoIndex:
    """One camera's frames in time order."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.paths: list[Path] = []
        self.gaps: list[Gap] = []
        # Every frame's moment ascending, its pts, its segment (into paths): views of
        # buffers that double as they fill, so a new segment copies only itself.
        self._buffers: list[np.ndarray] = [
            np.empty(0, np.int64),
            np.empty(0, np.int64),
            np.empty(0, np.int32),
        ]
        self._size = 0
        self.generation = 0  # counts the times the frames were sorted anew
        self.ms: np.ndarray = self._buffers[0]
        self._pts: np.ndarray = self._buffers[1]
        self._segment: np.ndarray = self._buffers[2]
        self._names: set[str] = set()
        self._gaps_size = 0
        self._listed = Appended(folder / SEGMENTS)
        self._unread: dict[str, int] = {}  # listed, times not read yet: the tries
        self.unreadable: list[str] = []  # given up: their frames are not here

    def __len__(self) -> int:
        return int(self.ms.size)

    def refresh(self) -> bool:
        """Segments closed since the last refresh added; True when any was."""
        self._read_gaps()
        names = [*self._unread, *self._listed.new_lines()]
        new = [self.folder / f"{n}.mkv" for n in names if f"{n}.mkv" not in self._names]
        read = [
            (path, times) for path in new if (times := read_times(path)) is not None
        ]
        for path, _ in read:
            self._names.add(path.name)
        # Times that cannot be read now -- held by their writer a moment -- next time;
        # still not after TRIES polls, the segment is given up and said.
        unread = {}
        for path in new:
            if path.name not in self._names:
                tries = self._unread.get(path.stem, 0) + 1
                if tries < TRIES:
                    unread[path.stem] = tries
                else:
                    self.unreadable.append(path.stem)
        self._unread = unread
        added = [(path, times) for path, times in read if len(times)]  # no frame: none
        if not added:
            return False
        first = len(self.paths)
        self.paths += [path for path, _ in added]
        segment = np.concatenate(
            [
                np.full(len(times), first + k, np.int32)
                for k, (_, times) in enumerate(added)
            ]
        )
        times = np.concatenate([times for _, times in added])
        self._append(times[:, 1], times[:, 0], segment)
        return True

    def nearest(self, ms: int, within: int | None = None) -> int | None:
        """The place of the frame nearest ``ms``; the earlier of two as near. None
        when there is none, or the nearest is further than ``within`` ms."""
        if not len(self):
            return None
        i = int(np.searchsorted(self.ms, ms))
        if i == len(self) or (i and ms - self.ms[i - 1] <= self.ms[i] - ms):
            i -= 1
        if within is not None and abs(int(self.ms[i]) - ms) > within:
            return None
        return i

    def around(self, ms: int) -> tuple[int, int] | None:
        """The places of the two frames ``ms`` lies between -- on a frame, it and the
        one before; None outside the recording."""
        after = int(np.searchsorted(self.ms, ms))
        if after == 0 or after >= len(self):
            return None
        return after - 1, after

    def step(self, place: int, frames: int) -> int:
        """The place ``frames`` on from ``place``, within the recording."""
        return min(max(place + frames, 0), len(self) - 1)

    def step_ms(self, place: int, ms: int) -> int:
        """The place of the frame nearest ``ms`` on from the frame at ``place``."""
        nearest = self.nearest(int(self.ms[place]) + ms)
        return place if nearest is None else nearest

    def find(self, frame: Frame) -> int | None:
        """A frame's place now: after the frames were sorted anew, it may differ."""
        try:
            segment = self.paths.index(frame.path)
        except ValueError:
            return None
        found = np.nonzero((self._segment == segment) & (self._pts == frame.pts))[0]
        return int(found[0]) if found.size else None

    def frame(self, place: int) -> Frame:
        place = min(max(place, 0), len(self) - 1)
        return Frame(
            self.paths[int(self._segment[place])],
            int(self._pts[place]),
            int(self.ms[place]),
        )

    def _append(self, ms: np.ndarray, pts: np.ndarray, segment: np.ndarray) -> None:
        if not ms.size:
            return
        later = not len(self) or ms.min() >= self.ms[-1]
        size, end = self._size, self._size + ms.size
        if end > self._buffers[0].size:
            room = max(end, 2 * self._buffers[0].size, 4096)
            grown = []
            for old in self._buffers:
                new = np.empty(room, old.dtype)
                new[:size] = old[:size]
                grown.append(new)
            self._buffers = grown
        for buffer, values in zip(self._buffers, (ms, pts, segment), strict=True):
            buffer[size:end] = values
        self._size = end
        if not later or not np.all(ms[:-1] <= ms[1:]):
            order = np.argsort(self._buffers[0][:end], kind="stable")
            for buffer in self._buffers:
                buffer[:end] = buffer[:end][order]
            self.generation += 1  # places held before name other frames now
        self.ms, self._pts, self._segment = (b[:end] for b in self._buffers)  # views

    def _read_gaps(self) -> None:
        path = self.folder / "gaps.txt"
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size == self._gaps_size:
            return
        self._gaps_size = size
        gaps = []
        for line in path.read_text(encoding="ascii", errors="replace").splitlines():
            start, _, rest = line.partition(" ")
            end, _, reason = rest.partition(" ")
            if start.isdigit() and end.isdigit():
                gaps.append(Gap(int(start), int(end), reason))
        self.gaps = gaps


def read_times(path: Path) -> np.ndarray | None:
    """A segment's ``<pts> <ms>`` pairs in time order; None when they cannot be read."""
    try:
        text = path.with_suffix(".times").read_text(encoding="ascii")
        pairs = np.array(text.split(), dtype=np.int64).reshape(-1, 2)
    except OSError, ValueError:
        return None
    return pairs[np.argsort(pairs[:, 1], kind="stable")]


class FileIndex(VideoIndex):
    """A camera's own recording opened after the race: one file, read once and never
    written. Its frames are placed from the file's creation time (or, without one,
    its modification time less its length) by their own timestamps; aligning it on a
    shared event puts it next to the live recordings. An hour of video takes a while
    to read: it is read on a thread of its own, and refresh hands its frames over
    once that is done."""

    def __init__(self, path: Path) -> None:
        super().__init__(path.parent)
        self.file = path
        self._reading: threading.Thread | None = None
        self._found: tuple[np.ndarray, np.ndarray] | None = None  # moments, pts
        self._handed = False

    def refresh(self) -> bool:
        if self._handed:
            return False
        if self._reading is None:
            self._reading = threading.Thread(target=self._read, daemon=True)
            self._reading.start()
        if self._reading.is_alive():
            return False
        self._handed = True
        if self._found is None:
            return False  # not a video: shown as a camera without frames
        ms, pts = self._found
        self.paths = [self.file]
        self._append(ms, pts, np.zeros(pts.size, np.int32))
        return True

    def _read(self) -> None:
        try:
            with av.open(str(self.file)) as container:
                stream = container.streams.video[0]
                rate = stream.time_base or Fraction(1, 1000)
                unit = float(Fraction(rate.numerator, rate.denominator)) * 1000
                found = [p.pts for p in container.demux(stream) if p.pts is not None]
                created = container.metadata.get("creation_time")
            if not found:
                return
            pts = np.array(sorted(found), np.int64)
            since = np.round((pts - pts[0]) * unit).astype(np.int64)
            start = _created_ms(created)
            if start is None:
                start = self.file.stat().st_mtime_ns // 1_000_000 - int(since[-1])
        except OSError, IndexError, av.FFmpegError:
            return
        self._found = start + since, pts


def _created_ms(created: str | None) -> int | None:
    """The creation time a camera wrote into its file, as Unix ms."""
    try:
        moment = datetime.fromisoformat(str(created))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return round(moment.timestamp() * 1000)
