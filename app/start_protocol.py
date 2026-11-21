"""The start numbers of a race's start protocol (specs/014-start-protocol).

StartProtocolMaker's ``start.txt`` holds a line a rider, ``#``-separated: the number
first, the number of stages fifth -- a relay of N stages runs number to number + N - 1,
as FinishProtocolGenerator counts them. A table with the number first, split at ``;``,
``,`` or a tab, is read too, as SportPhotoIndexer reads one. The file is only read.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from app.paths import app_path

ENCODINGS = ("utf-8-sig", "cp1251", "latin-1")  # as the older tools wrote them
SEPARATORS = re.compile("[#;,\t]")


def loose(number: str) -> str:
    """A number as numbers are compared: upper case, a run of digits without its
    leading zeros -- "007" is 7, "a012" A12 -- as a plate and a protocol may differ."""
    return re.sub(r"(?<!\d)0+(?=\d)", "", number.upper())


def read_numbers(path: Path) -> dict[str, str]:
    """The protocol's numbers, each by its loose form, spelled as the protocol spells
    it. A first field without a digit -- a header, an unpaid marker -- is no number.
    Raises OSError when the file cannot be read."""
    data = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    numbers: dict[str, str] = {}
    for line in text.splitlines():
        fields = SEPARATORS.split(line)
        number = fields[0].strip().strip("\"'")
        if not any(c.isdigit() for c in number):
            continue
        numbers.setdefault(loose(number), number)
        for stage in _stages(line, fields, number):
            numbers.setdefault(loose(stage), stage)
    return numbers


def _stages(line: str, fields: list[str], number: str) -> list[str]:
    """A relay's numbers after its first: a StartProtocolMaker line's fifth field of
    N > 1 stages, its number a number."""
    if not number.isdigit() or line.count("#") < 5:
        return []
    stages = fields[4].strip()
    count = int(stages) if stages.isdigit() else 1
    return [str(int(number) + k) for k in range(1, count)]


class StartNumbers:
    """The numbers of the protocol at ``path()``, read again when the path, or the
    file's size or time, changes; {} without one, or when it cannot be read --
    ``problem`` says why."""

    def __init__(self, path: Callable[[], str]) -> None:
        self.path = path
        self._seen: tuple[str, int, int] | None = None
        self._numbers: dict[str, str] = {}
        self.problem = ""

    def __call__(self) -> dict[str, str]:
        chosen = self.path()
        if not chosen:
            self._seen, self._numbers, self.problem = None, {}, ""
            return {}
        file = app_path(chosen)
        try:
            stat = file.stat()
            seen = (chosen, stat.st_size, stat.st_mtime_ns)
            if seen != self._seen:
                self._numbers, self._seen = read_numbers(file), seen
            self.problem = ""
        except OSError as error:
            self._seen, self._numbers = None, {}
            self.problem = f"the start protocol cannot be read: {error}"
        return self._numbers
