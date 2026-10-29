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

import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from app import files
from app.lines import parse_line, text_lines
from app.output_list import OutputList

REST_NS = 2_000_000_000  # a last line left without its line break this long is done


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
    common with it is a new file -- a new competition at the chronometer -- all new;
    otherwise a line the chronometer edited keeps the content taken until copied."""
    result = Alignment()
    if taken and current and set(taken).isdisjoint(current):
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
    """An edit at the chronometer keeps a crossing's number or its time."""
    a, b = parse_line(taken), parse_line(current)
    return a.number == b.number or (a.ms is not None and a.ms == b.ms)


class InputFollow:
    """The input file followed into the output list; the window polls it."""

    def __init__(self, path: Path, output: OutputList) -> None:
        self.path = path
        self.output = output
        self.lines: list[InputLine] = []
        self._seen: tuple[int, int, int] | None = None
        self._cut = False  # the last read ended in a line without its line break

    def poll(self) -> bool:
        """Read the input again when it changed, or when a last line without its line
        break has been left as it is for REST_NS; True when it was read."""
        # shortcut: a rewrite keeping the size within one tick of the file system's
        # clock (15 ms on Windows) is seen at the next change; poll by content if a
        # chronometer ever edits that fast.
        try:
            stat = self.path.stat()
            seen = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            at_rest = time.time_ns() - stat.st_mtime_ns > REST_NS
            if seen == self._seen and not (self._cut and at_rest):
                return False
            data = files.read_bytes(self.path)
        except OSError:
            return False  # not there, or held by its writer a moment: next time
        complete = data[: data.rfind(b"\n") + 1]
        cut = len(complete) < len(data) and bool(data[len(complete) :].strip())
        # A line still being written waits for its line break; one a tool or a hand
        # left without it is taken once the file has rested.
        current = text_lines(data if cut and at_rest else complete)
        result = align(self.output.taken, current)
        self.output.follow(result.taken, result.new, result.gone)
        self.lines = result.shown
        self._seen, self._cut = seen, cut and not at_rest
        return True

    def copy(self, index: int) -> int:
        """ "Copy to output": the changed line ``index`` applied by hand; its index in
        the output."""
        line = self.lines[index]
        if line.taken is None:
            raise ValueError("the line is as it was taken")
        at = self.output.copy_input(index, line.text)
        self.lines[index] = InputLine(line.text)
        return at
