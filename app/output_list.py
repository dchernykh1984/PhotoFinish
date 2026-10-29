"""The referee's crossings: the output file, its state and its journal.

The output file holds ``number#time#action#`` lines in time order, stable, the lines
without a readable time after them in the order they came: FinishProtocolGenerator
reads it as a finish file. Beside it, ``<output>.state.json`` keeps each line's
origin and marks, and ``<output>.journal.txt`` gets one JSON object per change
(contracts/output-and-journal.md). A line taken from the input keeps its text until
the referee changes it.

Every change writes the state, then the output file, each in one step. A version of
the output something else wrote is kept in a backup and journaled before it is
replaced; the window calls ``check_outside`` as it polls, and every change checks
first.
"""

from __future__ import annotations

import copy
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.lines import parse_line, scale_time, text_lines

_STATE_VERSION = 1
_RENAME_TRIES = 5


@dataclass
class OutputLine:
    """A line of the output: its text, where it came from, how its time was had."""

    text: str
    origin: dict[str, Any]
    method: str
    removed_from_input: bool = False


@dataclass
class Change:
    """How a time was had, for the journal: the method, the camera, the frames as
    ``[segment, pts, ms]``, the fraction between two of them, the offsets in use."""

    method: str
    camera: str | None = None
    frames: list[list[Any]] = field(default_factory=list)
    fraction: float | None = None
    offsets: dict[str, int] = field(default_factory=dict)


def clean_number(number: str) -> str:
    """A typed number fit for the first field: no ``#`` and no line break of any
    kind, or the line would read back as more than one crossing."""
    return " ".join(number.replace("#", " ").splitlines()).strip()


class OutputList:
    """The output list over its file: every change is on disk at once, journaled."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.state_path = path.with_name(path.name + ".state.json")
        self.journal_path = path.with_name(path.name + ".journal.txt")
        self.lines: list[OutputLine] = []
        self._written: bytes | None = None  # the output file as this list wrote it
        self._load()

    def texts(self) -> list[str]:
        return [line.text for line in self.lines]

    # -- changes ---------------------------------------------------------------

    def take(self, text: str) -> int:
        """An input line, taken as it is; its index."""
        with self._change():
            at = self._insert(OutputLine(text, {"input": text}, "input"))
            self._journal("take", after=text, input_text=text, change=Change("input"))
        return at

    def add(self, number: str, ms: int, action: str, change: Change) -> int:
        """A crossing the referee timed, ``ms`` on the line scale; its index."""
        text = f"{_number(number)}#{scale_time(ms)}#{action}#"
        with self._change():
            at = self._insert(OutputLine(text, {"added": True}, change.method))
            self._journal("add", after=text, change=change)
        return at

    def set_time(self, index: int, ms: int, change: Change) -> int:
        """A line's time, its other fields as they are; its new index."""
        fields = self.lines[index].text.split("#")
        fields += [""] * (3 - len(fields))  # a line without a time field gets one
        fields[1] = scale_time(ms)
        return self._replace(index, "#".join(fields), "time", change)

    def set_number(self, index: int, number: str) -> int:
        """A line's number, its other fields as they are; its index."""
        line = self.lines[index]
        fields = line.text.split("#")
        fields[0] = _number(number)
        return self._replace(index, "#".join(fields), "number", Change(line.method))

    def remove(self, index: int) -> None:
        """A false crossing leaves the output; the journal keeps it."""
        with self._change():
            line = self.lines.pop(index)
            before, taken = line.text, line.origin.get("input")
            self._journal("remove", before=before, input_text=taken)

    def copy_input(self, taken: str, current: str) -> int:
        """A changed input line applied by hand: the output line taken as ``taken``
        becomes ``current``, or ``current`` comes back when the referee had removed
        that line. Its index."""
        index = self._from_input(taken)
        if index is not None:
            return self._replace(index, current, "copy", Change("input"), current)
        with self._change():
            at = self._insert(OutputLine(current, {"input": current}, "input"))
            self._journal(
                "copy", after=current, input_text=current, change=Change("input")
            )
        return at

    def mark_removed(self, taken: str) -> None:
        """The input line ``taken`` is gone: its output line stays, marked."""
        for line in self.lines:
            if line.origin.get("input") == taken and not line.removed_from_input:
                line.removed_from_input = True
                self._write_state()
                return

    def check_outside(self) -> bool:
        """True when something else wrote the output file: its version is kept in a
        backup and journaled, and the list is written again."""
        if not self._keep_outside_version():
            return False
        self._write()
        return True

    # -- inside ----------------------------------------------------------------

    @contextmanager
    def _change(self) -> Iterator[None]:
        """One change, written at once. A version of the file something else wrote is
        kept first; a change that cannot be written leaves the list as it was."""
        self._keep_outside_version()
        kept = copy.deepcopy(self.lines)
        try:
            yield
            self._write()
        except BaseException:
            self.lines = kept
            raise

    def _replace(
        self, index: int, text: str, op: str, change: Change, taken: str | None = None
    ) -> int:
        with self._change():
            line = self.lines.pop(index)
            before, line.text, line.method = line.text, text, change.method
            if taken is not None:
                line.origin, line.removed_from_input = {"input": taken}, False
            at = self._insert(line)
            self._journal(
                op,
                before=before,
                after=text,
                input_text=line.origin.get("input"),
                change=change,
            )
        return at

    def _from_input(self, taken: str) -> int | None:
        """The output line taken as ``taken``. Of two taken alike, one the referee left
        as it was: an edit belongs to one line, not to its twin."""
        found = [
            i for i, ln in enumerate(self.lines) if ln.origin.get("input") == taken
        ]
        first = found[0] if found else None
        return next((i for i in found if self.lines[i].text == taken), first)

    def _insert(self, line: OutputLine) -> int:
        """In time order, after the lines of its time; a line without a time last."""
        ms = parse_line(line.text).ms
        at = len(self.lines)
        if ms is not None:
            later = (i for i, other in enumerate(self.lines) if _goes_after(other, ms))
            at = next(later, at)
        self.lines.insert(at, line)
        return at

    def _load(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.lines = [OutputLine(**entry) for entry in state["lines"]]
        except FileNotFoundError:
            self._adopt()
            return
        except ValueError, KeyError, TypeError:
            # Not a state: kept aside, and the file's crossings start the list again.
            self.state_path.replace(_aside(self.state_path, "broken"))
            self._adopt()
            return
        self._written = self._body()
        self.check_outside()

    def _adopt(self) -> None:
        """No state: crossings already in the file start the list, in time order, and
        the file as it was is kept in a backup and journaled."""
        found = _read(self.path)
        self.lines = []
        for text in text_lines(found or b""):
            self._insert(OutputLine(text, {"outside": True}, "outside"))
        self._written = None if self.lines else found
        if not self.check_outside():
            self._write()

    def _keep_outside_version(self) -> bool:
        current = _read(self.path)
        if current == self._written:
            return False
        backup = None
        if current is not None:
            backup = _aside(self.path, "outside")
            _write_in_one_step(backup, current)
        self._journal("outside_change", backup=backup.name if backup else None)
        return True

    def _write(self) -> None:
        """The state, then the output file, each in one step: after a crash between
        the two, the state is ahead and writes the file again at the next start."""
        self._write_state()
        body = self._body()
        _write_in_one_step(self.path, body)
        self._written = body

    def _write_state(self) -> None:
        lines = [asdict(line) for line in self.lines]
        state = {"version": _STATE_VERSION, "lines": lines}
        text = json.dumps(state, ensure_ascii=False) + "\n"
        _write_in_one_step(self.state_path, text.encode())

    def _body(self) -> bytes:
        return "".join(f"{text}\n" for text in self.texts()).encode()

    def _journal(
        self,
        op: str,
        *,
        before: str | None = None,
        after: str | None = None,
        input_text: str | None = None,
        change: Change | None = None,
        backup: str | None = None,
    ) -> None:
        at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        entry: dict[str, Any] = {
            "at": at,
            "op": op,
            "before": before,
            "after": after,
            "input": input_text,
        }
        if change is not None:
            entry |= {
                "camera": change.camera,
                "frames": change.frames or None,
                "method": change.method,
                "fraction": change.fraction,
                "offsets": change.offsets or None,
            }
        entry["backup"] = backup
        kept = {key: value for key, value in entry.items() if value is not None}
        _append(
            self.journal_path, (json.dumps(kept, ensure_ascii=False) + "\n").encode()
        )


def _number(number: str) -> str:
    cleaned = clean_number(number)
    if not cleaned:
        raise ValueError("a crossing needs a number")
    return cleaned


def _goes_after(line: OutputLine, ms: int) -> bool:
    """True when ``line`` goes after a crossing at ``ms``: later, or without a time."""
    other = parse_line(line.text).ms
    return other is None or other > ms


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _aside(path: Path, why: str) -> Path:
    return path.with_name(f"{path.name}.{why}-{datetime.now():%Y%m%d-%H%M%S-%f}")


def _write_in_one_step(path: Path, data: bytes) -> None:
    """A temporary file, flushed and synced, renamed over: a reader sees the old file
    or the new one, never a mix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(_RENAME_TRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            # Windows refuses while a reader, or a virus scanner, holds the file.
            if attempt == _RENAME_TRIES - 1:
                raise
            time.sleep(0.05)


def _append(path: Path, data: bytes) -> None:
    """``data`` at the end of ``path``, synced; after a line a crash cut short, on a
    line of its own."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        end = f.seek(0, os.SEEK_END)
        if end:
            f.seek(end - 1)
            if f.read(1) != b"\n":
                data = b"\n" + data
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
