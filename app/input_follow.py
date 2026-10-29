"""The chronometer's file, followed into the output list.

The input is read only (FR-001): opened when its size, time or identity changed,
read whole and let go at once, its complete lines only. It is aligned with the
input as last taken, which the output keeps in its state: lines that were added are
taken into the output; lines that changed are held back and shown with both
contents until the referee copies them; lines that are gone leave their output
lines marked. A file that is not there is no empty file: nothing is marked gone
while a stick is out.
"""

from __future__ import annotations

import bisect
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from app import files
from app.lines import decoded_lines, parse_line
from app.output_list import JournalError, OutputList

REST_NS = 2_000_000_000  # a last line left without its line break this long is done
NEW_FILE_MS = 10 * 60_000  # a new file's crossings are further than this from the old
EDIT_MS = 10_000  # an edit at the chronometer moves a crossing's time this far at most


@dataclass(frozen=True)
class InputLine:
    """A line of the input as it is; ``taken`` is what was taken from it when the
    chronometer changed it since, None when it is as taken."""

    text: str
    taken: str | None = None


@dataclass
class Alignment:
    """The input against the input as last taken."""

    taken: list[str] = field(default_factory=list)  # the input as taken from now on
    new: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)
    shown: list[InputLine] = field(default_factory=list)  # line by line, as taken

    def add(self, text: str) -> None:
        self.taken.append(text)
        self.new.append(text)
        self.shown.append(InputLine(text))


def align(taken: list[str], current: list[str]) -> Alignment:
    """``current`` against the input as last ``taken``. An input with no line in
    common with it and no crossing near one taken is a new file -- a new competition
    at the chronometer -- all new; otherwise a line the chronometer edited keeps the
    content taken until copied."""
    result = Alignment()
    if _new_file(taken, current):
        result.gone = list(taken)
        for text in current:
            result.add(text)
        return result
    matcher = SequenceMatcher(None, taken, current, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.taken += current[j1:j2]
            result.shown += [InputLine(text) for text in current[j1:j2]]
        else:
            _pair(taken[i1:i2], current[j1:j2], result)
    return result


def _new_file(taken: list[str], current: list[str]) -> bool:
    """No line in common, and no crossing within NEW_FILE_MS of one taken: the
    chronometer began a file anew. An edit keeps its crossings near their times."""
    if not taken or not current or not set(taken).isdisjoint(current):
        return False
    before = sorted(ms for text in taken if (ms := parse_line(text).ms) is not None)
    for text in current:
        ms = parse_line(text).ms
        if ms is None or not before:
            continue
        i = bisect.bisect_left(before, ms)
        if min(abs(ms - before[j]) for j in (i - 1, i) if 0 <= j < len(before)) <= (
            NEW_FILE_MS
        ):
            return False
    return True


def _pair(before: list[str], after: list[str], result: Alignment) -> None:
    """A stretch that differs: each line taken pairs, in order, with the next line
    that is the same crossing edited; lines left over are gone or new."""
    j = 0
    for text in before:
        edited = (k for k in range(j, len(after)) if _same_crossing(text, after[k]))
        k = next(edited, None)
        if k is None:
            result.gone.append(text)
            continue
        for added in after[j:k]:
            result.add(added)
        result.taken.append(text)
        result.shown.append(InputLine(after[k], text))
        j = k + 1
    for added in after[j:]:
        result.add(added)


def _same_crossing(taken: str, current: str) -> bool:
    """An edit at the chronometer keeps a crossing's time, or its number with a time
    near it: the same rider's lap later on is another crossing."""
    a, b = parse_line(taken), parse_line(current)
    if a.ms is not None and a.ms == b.ms:
        return True
    if a.number != b.number:
        return False
    return a.ms is None or b.ms is None or abs(a.ms - b.ms) <= EDIT_MS


class InputFollow:
    """The input file followed into the output list; the window polls it."""

    def __init__(self, path: Path, output: OutputList) -> None:
        self.path = path
        self.output = output
        self.lines: list[InputLine] = []
        self._seen: tuple[int, int, int] | None = None  # the file as last read
        self._looked: tuple[int, int, int] | None = None  # as last looked at
        self._since = 0  # this computer's steady clock, ns: when it was first so
        self._cut = False  # the last read ended in a line without its line break
        self.encodings: dict[str, str] = {}  # each line read, the encoding it came in

    def poll(self) -> bool:
        """Read the input again when it changed, or when a last line without its line
        break has been left as it is for REST_NS; True when it was read."""
        # shortcut: a rewrite keeping the size within one tick of the file system's
        # clock (15 ms on Windows) is seen at the next change; poll by content if a
        # chronometer ever edits that fast.
        try:
            stat = self.path.stat()
            seen = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            now = time.monotonic_ns()
            if seen != self._looked:
                self._looked, self._since = seen, now
            # At rest by this computer's clock, not the file's time: a stick's FAT
            # keeps it in 2 s steps, a share's server by a clock of its own.
            at_rest = now - self._since > REST_NS
            if seen == self._seen and not (self._cut and at_rest):
                return False
            if self._seen and seen[0] < self._seen[0] and not at_rest:
                return False  # shorter, still changing: a rewrite half done, maybe
            data = files.read_bytes(self.path)
        except OSError:
            return False  # not there, or held by its writer a moment: next time
        complete = data[: data.rfind(b"\n") + 1]
        cut = len(complete) < len(data) and bool(data[len(complete) :].strip())
        # A line still being written waits for its line break; one a tool or a hand
        # left without it is taken once the file has rested.
        found = decoded_lines(data if cut and at_rest else complete)
        current = [text for text, _ in found]
        self.encodings = {text: encoding for text, encoding in found}
        result = align(self.output.taken, current)
        journal = None
        try:
            self.output.follow(result.taken, result.new, result.gone, self.encodings)
        except JournalError as error:  # the lines are taken all the same
            journal = error
        self.lines = result.shown
        self._seen, self._cut = seen, cut and not at_rest
        if journal is not None:
            raise journal
        return True

    def copy(self, index: int) -> int:
        """ "Copy to output": the changed line ``index`` applied by hand; its index in
        the output. A copy the journal cannot take is written all the same."""
        line = self.lines[index]
        if line.taken is None:
            raise ValueError("the line is as it was taken")
        journal, at = None, index
        try:
            encoding = self.encodings.get(line.text, "utf-8")
            at = self.output.copy_input(index, line.text, encoding)
        except JournalError as error:  # copied all the same
            journal = error
        self.lines[index] = InputLine(line.text)
        if journal is not None:
            raise journal
        return at
