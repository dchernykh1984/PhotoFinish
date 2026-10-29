"""The referee's crossings: the output file, its state and its journal.

The output file holds ``number#time#action#`` lines in time order, stable, the lines
without a readable time after them in the order they came: FinishProtocolGenerator
reads it as a finish file. Beside it, ``<output>.state.json`` keeps each line's
origin and marks with the input as last taken, so the two are written together, and
``<output>.journal.txt`` gets one JSON object per change
(contracts/output-and-journal.md). A line taken from the input keeps its text until
the referee changes it.

Every change writes the state, then the output file, each in one step. A version of
the output something else wrote is kept in a backup and journaled before it is
replaced; the window calls ``check_outside`` as it polls, and every change checks
first.
"""

from __future__ import annotations

import copy
import functools
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app import files
from app.files import write_in_one_step as _write_in_one_step
from app.lines import parse_line, scale_time, text_lines

_STATE_VERSION = 1


@dataclass
class OutputLine:
    """A line of the output: its text, where it came from, how its time was had."""

    text: str
    origin: dict[str, Any]
    method: str
    removed_from_input: bool = False


class JournalError(OSError):
    """The change is written to the output and its state; its journal entries are
    not. Not a failed change: doing it again would do it twice."""


@dataclass
class Change:
    """How a time was had, for the journal: the method, the camera, the frames as
    ``[segment, pts, ms]``, the fraction between two of them, the offsets in use."""

    method: str
    camera: str | None = None
    frames: list[list[Any]] = field(default_factory=list)
    fraction: float | None = None
    offsets: dict[str, int] = field(default_factory=dict)
    model: str | None = None  # a crossing a detection model suggested (002)


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
        self.taken: list[str] = []  # the input as last taken, in its order
        self._pending: list[bytes] | None = None  # journal entries of a change
        self._written: bytes | None = None  # the output file as this list wrote it
        self._written_stat: tuple[int, int, int] | None = None  # its size, time, inode
        self._load()

    def texts(self) -> list[str]:
        return [line.text for line in self.lines]

    # -- changes ---------------------------------------------------------------

    def follow(self, taken: list[str], new: list[str], gone: list[str]) -> None:
        """The input aligned (app/input_follow.py): ``gone`` lines marked on their
        output lines, ``new`` lines taken, ``taken`` the input as taken from now on.
        Gone first: a line that moved in the input is found again, not taken twice."""
        if taken == self.taken and not new and not gone:
            return
        with self._change():
            for text in gone:
                self._mark_gone(text)
            for text in new:
                if not self._found_again(text):
                    self._insert(OutputLine(text, {"input": text}, "input"))
                    self._journal(
                        "take", after=text, input_text=text, change=Change("input")
                    )
            self.taken = list(taken)

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
        with self._change():
            at = self._replace(index, "#".join(fields), "time", change)
        return at

    def set_number(self, index: int, number: str) -> int:
        """A line's number, its other fields as they are; its index."""
        line = self.lines[index]
        fields = line.text.split("#")
        fields[0] = _number(number)
        with self._change():
            at = self._replace(index, "#".join(fields), "number", Change(line.method))
        return at

    def remove(self, index: int) -> None:
        """A false crossing leaves the output; the journal keeps it."""
        with self._change():
            line = self.lines.pop(index)
            before, taken = line.text, line.origin.get("input")
            self._journal("remove", before=before, input_text=taken)

    def copy_input(self, index: int, current: str) -> int:
        """Line ``index`` of the input as taken changed to ``current``, applied by hand:
        its output line becomes ``current``, or ``current`` comes back when the referee
        had removed that line. Its index in the output."""
        found = self._from_input(self.taken[index])
        with self._change():
            self.taken[index] = current
            if found is not None:
                at = self._replace(found, current, "copy", Change("input"), current)
            else:
                at = self._insert(OutputLine(current, {"input": current}, "input"))
                self._journal(
                    "copy", after=current, input_text=current, change=Change("input")
                )
        return at

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
        """One change, written at once and then journaled. A version of the file
        something else wrote is kept first. A change that cannot be written leaves
        the list as it was, its state file too, and nothing in the journal; a journal
        that cannot take the entries of a change written is an error said, the
        change kept."""
        self._keep_outside_version()
        kept = copy.deepcopy((self.lines, self.taken))
        self._pending = []
        try:
            yield
            self._write()
        except BaseException:
            self.lines, self.taken, self._pending = kept[0], kept[1], None
            self._write_state_back()
            raise
        entries, self._pending = self._pending, None
        if entries:
            try:
                _append(self.journal_path, b"".join(entries))
            except OSError as error:
                raise JournalError(str(error)) from error

    def _replace(
        self, index: int, text: str, op: str, change: Change, taken: str | None = None
    ) -> int:
        line = self.lines[index]
        before, line.text, line.method = line.text, text, change.method
        if taken is not None:
            line.origin, line.removed_from_input = {"input": taken}, False
        at = index
        if _time_of(text) != _time_of(before):  # a new time: a new place; else none
            at = self._insert(self.lines.pop(index))
        self._journal(
            op,
            before=before,
            after=text,
            input_text=line.origin.get("input"),
            change=change,
        )
        return at

    def _found_again(self, text: str) -> bool:
        """A new input line the output has already: one marked gone whose input line
        is back, or one found in the file when it was chosen. No second line."""
        for line in self.lines:
            if line.origin.get("input") == text and line.removed_from_input:
                line.removed_from_input = False
                return True
        for line in self.lines:
            if line.origin.get("outside") and line.text == text:
                line.origin, line.method = {"input": text}, "input"
                return True
        return False

    def _mark_gone(self, text: str) -> None:
        for line in self.lines:
            if line.origin.get("input") == text and not line.removed_from_input:
                line.removed_from_input = True
                return

    def _from_input(self, taken: str) -> int | None:
        """The output line taken as ``taken``. Of two taken alike, one the referee left
        as it was: an edit belongs to one line, not to its twin."""
        found = [
            i for i, ln in enumerate(self.lines) if ln.origin.get("input") == taken
        ]
        first = found[0] if found else None
        return next((i for i in found if self.lines[i].text == taken), first)

    def _insert(self, line: OutputLine) -> int:
        """In time order, after the lines of its time; a line without a time last.
        Looked for from the end, where a new crossing nearly always goes."""
        ms = _time_of(line.text)
        at = len(self.lines)
        if ms is not None:
            at = 0
            for i in range(len(self.lines) - 1, -1, -1):
                other = _time_of(self.lines[i].text)
                if other is not None and other <= ms:
                    at = i + 1
                    break
        self.lines.insert(at, line)
        return at

    def _load(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.lines = [OutputLine(**entry) for entry in state["lines"]]
            self.taken = [str(text) for text in state["input_taken"]]
        except FileNotFoundError:
            self._start_from_file()
            return
        except ValueError, KeyError, TypeError:
            # Not a state: kept aside. The file's crossings start the list again, and
            # the input as taken is what the journal says was taken, so a line the
            # referee corrected does not come back beside its correction.
            self.state_path.replace(_aside(self.state_path, "broken"))
            self._start_from_file(_taken_in(self.journal_path))
            return
        self._written = self._body()
        self.check_outside()

    def _start_from_file(self, taken: list[str] | None = None) -> None:
        """No state: crossings already in the file start the list, in time order, and
        the file as it was is kept in a backup and journaled."""
        found = _read(self.path)
        self.lines, self.taken = [], taken or []
        for text in text_lines(found or b""):
            self._insert(OutputLine(text, {"outside": True}, "outside"))
        self._written = None if self.lines else found
        if not self.check_outside():
            self._write()

    def _keep_outside_version(self) -> bool:
        # shortcut: a file rewritten in place, its size kept, within one tick of the
        # file system's clock, is read at the next change; read on every poll then.
        stat = _stat(self.path)
        if stat is not None and stat == self._written_stat:
            return False  # as this list wrote it: not read again
        current = _read(self.path)
        if current == self._written:
            self._written_stat = stat
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
        _write_in_one_step(self.state_path, self._state())
        body = self._body()
        _write_in_one_step(self.path, body)
        self._written, self._written_stat = body, _stat(self.path)

    def _state(self) -> bytes:
        lines = [asdict(line) for line in self.lines]
        state = {"version": _STATE_VERSION, "lines": lines, "input_taken": self.taken}
        return (json.dumps(state, ensure_ascii=False) + "\n").encode()

    def _write_state_back(self) -> None:
        """After a change that failed: the state as the list is again, so a restart
        does not bring back what the referee was told was not written."""
        try:
            _write_in_one_step(self.state_path, self._state())
        except OSError:
            pass  # the disk itself refuses: the state is as the last change left it

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
                "model": change.model,
            }
        entry["backup"] = backup
        kept = {key: value for key, value in entry.items() if value is not None}
        line = (json.dumps(kept, ensure_ascii=False) + "\n").encode()
        if self._pending is None:
            _append(self.journal_path, line)
        else:
            self._pending.append(line)  # journaled once the change is written


def _number(number: str) -> str:
    cleaned = clean_number(number)
    if not cleaned:
        raise ValueError("a crossing needs a number")
    return cleaned


def _taken_in(journal: Path) -> list[str]:
    """The input lines the journal says were taken, in order; a copy in place of the
    line it changed."""
    taken: list[str] = []
    for raw in (_read(journal) or b"").splitlines():
        try:
            entry = json.loads(raw)
            op, given = entry.get("op"), entry.get("input")
        except ValueError, AttributeError:
            continue
        if op == "copy" and given and entry.get("before") in taken:
            taken[taken.index(entry["before"])] = given
        elif op in ("take", "copy") and given:
            taken.append(given)
    return taken


@functools.lru_cache(maxsize=1 << 16)
def _time_of(text: str) -> int | None:
    """A line's time, parsed once however often the list is ordered."""
    return parse_line(text).ms


def _stat(path: Path) -> tuple[int, int, int] | None:
    try:
        found = path.stat()
    except OSError:
        return None
    return found.st_size, found.st_mtime_ns, found.st_ino


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _aside(path: Path, why: str) -> Path:
    return path.with_name(f"{path.name}.{why}-{datetime.now():%Y%m%d-%H%M%S-%f}")


def _append(path: Path, data: bytes) -> None:
    """``data`` at the end of ``path``, synced; after a line a crash cut short, on a
    line of its own. A file held a moment (Windows) is tried again."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(files.TRIES):
        try:
            with path.open("a+b") as f:
                end = f.seek(0, os.SEEK_END)
                if end:
                    f.seek(end - 1)
                    if f.read(1) != b"\n":
                        data = b"\n" + data
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            return
        except PermissionError:
            if attempt == files.TRIES - 1:
                raise
            time.sleep(files.PAUSE_S)
