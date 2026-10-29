"""A camera's recorded frames: closed segments, frame times and gaps.

The window refreshes a camera's index as it polls: segments closed since -- the new
names in the recorder's ``segments.txt`` -- are read from their ``.times`` and
appended. Frame times are kept in numpy arrays in time
order, so the frame nearest a moment is a binary search, and a frame is named by
its place in that order. Gaps come from ``gaps.txt``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from app.files import Appended
from app.recorder.segments import SEGMENTS


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
        self.ms = np.empty(0, np.int64)  # every frame's moment, ascending
        self._pts = np.empty(0, np.int64)
        self._segment = np.empty(0, np.int32)  # into paths
        self._names: set[str] = set()
        self._gaps_size = 0
        self._listed = Appended(folder / SEGMENTS)
        self._unread: list[str] = []  # listed segments whose times were not read

    def __len__(self) -> int:
        return int(self.ms.size)

    def refresh(self) -> bool:
        """Segments closed since the last refresh added; True when any was."""
        self._read_gaps()
        names = self._unread + self._listed.new_lines()
        new = [self.folder / f"{n}.mkv" for n in names if f"{n}.mkv" not in self._names]
        added = [(path, times) for path in new if (times := _times(path)) is not None]
        for path, _ in added:
            self._names.add(path.name)
        # Times that cannot be read now -- held by their writer a moment -- next time.
        self._unread = [p.stem for p in new if p.name not in self._names]
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

    def nearest(self, ms: int) -> int | None:
        """The place of the frame nearest ``ms``; the earlier of two as near."""
        if not len(self):
            return None
        i = int(np.searchsorted(self.ms, ms))
        if i == 0:
            return 0
        if i == len(self) or ms - self.ms[i - 1] <= self.ms[i] - ms:
            return i - 1
        return i

    def step(self, place: int, frames: int) -> int:
        """The place ``frames`` on from ``place``, within the recording."""
        return min(max(place + frames, 0), len(self) - 1)

    def step_ms(self, place: int, ms: int) -> int:
        """The place of the frame nearest ``ms`` on from the frame at ``place``."""
        nearest = self.nearest(int(self.ms[place]) + ms)
        return place if nearest is None else nearest

    def frame(self, place: int) -> Frame:
        place = min(max(place, 0), len(self) - 1)
        return Frame(
            self.paths[int(self._segment[place])],
            int(self._pts[place]),
            int(self.ms[place]),
        )

    def _append(self, ms: np.ndarray, pts: np.ndarray, segment: np.ndarray) -> None:
        later = not len(self) or ms.min() >= self.ms[-1]
        self.ms = np.concatenate([self.ms, ms])
        self._pts = np.concatenate([self._pts, pts])
        self._segment = np.concatenate([self._segment, segment])
        if not later or not np.all(ms[:-1] <= ms[1:]):
            order = np.argsort(self.ms, kind="stable")
            self.ms, self._pts = self.ms[order], self._pts[order]
            self._segment = self._segment[order]

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


def _times(path: Path) -> np.ndarray | None:
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
    shared event puts it next to the live recordings."""

    def __init__(self, path: Path) -> None:
        super().__init__(path.parent)
        self.file = path
        self._read = False

    def refresh(self) -> bool:
        if self._read:
            return False
        self._read = True
        try:
            with av.open(str(self.file)) as container:
                stream = container.streams.video[0]
                rate = stream.time_base or Fraction(1, 1000)
                unit = float(Fraction(rate.numerator, rate.denominator)) * 1000
                found = [p.pts for p in container.demux(stream) if p.pts is not None]
                created = container.metadata.get("creation_time")
        except OSError, IndexError, av.FFmpegError:
            return False  # not a video: shown as a camera without frames
        if not found:
            return False
        pts = np.array(sorted(found), np.int64)
        since = np.round((pts - pts[0]) * unit).astype(np.int64)
        start = _created_ms(created)
        if start is None:
            start = self.file.stat().st_mtime_ns // 1_000_000 - int(since[-1])
        self.paths = [self.file]
        self._append(start + since, pts, np.zeros(pts.size, np.int32))
        return True


def _created_ms(created: str | None) -> int | None:
    """The creation time a camera wrote into its file, as Unix ms."""
    try:
        moment = datetime.fromisoformat(str(created))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return round(moment.timestamp() * 1000)
