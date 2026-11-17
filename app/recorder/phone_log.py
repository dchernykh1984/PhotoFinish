"""The phone's log, kept beside its camera's recording (specs/008-phone-log).

PhotoFinish Camera sends what it meets -- its start, the cameras it opens, their error
codes, the exceptions it catches, its own part of the system log -- over UDP to the port
its clock exchange is answered on, a line a line: ``PFLG 1 <run> <from> <prev>``, then
``<seq> <ms> <level> <lens> <text>`` lines. The recorder keeps them in ``phone.log`` in
the camera's folder, in the phone's order and each once, and answers ``PFLG 1 <run>
<seq>``, the newest it kept, so the phone sends again what was lost on the way
(specs/003-phone-camera-app/contracts/phone-stream.md).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

TAG = b"PFLG"
VERSION = "1"
FILE = "phone.log"
KEEP_BYTES = 10 * 1024 * 1024  # then kept as phone.log.1, and a new one begun
SAID_MS = 60_000  # a phone's last word shown on a camera's line this long
_RUN = re.compile(r"[0-9a-f]{16}")
# The app's own levels, I W E; its phone's system log's, w e (contract).
_LINE = re.compile(r"(\d+) (\d+) ([IWEwe]) (\S+) (.*)")
_MARK = re.compile(r"--- run ([0-9a-f]{16}) from line (\d+)")
_SEQ = re.compile(r"\S+ \S+ [IWEwe] \S+ #(\d+) ")


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class PhoneLog:
    """A camera's part of its phone's log: the lines of the camera's ``lens``, or of the
    phone as a whole, for its last word; every line for the file."""

    def __init__(
        self,
        folder: Path,
        lens: str | None = None,
        clock: Callable[[], int] = _now_ms,
    ) -> None:
        self.path, self.lens, self.clock = folder / FILE, lens, clock
        # Where the file is: a recorder started again goes on from its last line.
        self.run, self.kept = _where(self.path)
        # The phone's newest warning or error of this lens, or of the phone as a whole,
        # and when it came by this computer's clock: for the window (FR-005).
        self.said: dict[str, Any] = {}

    def heard(self, message: bytes) -> bytes | None:
        """The answer to ``message``, its lines kept; None when it is no log message.
        A round's first message (``prev`` the line before ``from``) begins a run not
        heard, and says when the phone no longer keeps the lines after the newest
        kept; another follows the message before it, which, lost on the way, the
        phone sends again. Gaps between a message's lines are lines the phone let go
        of: passed over."""
        read = _read(message)
        if read is None:
            return None
        run, start, prev, lines = read
        known = self.kept if run == self.run else None
        first = prev == start - 1
        written: list[str] = []
        if known is None or (first and start > known + 1):
            if not first:  # a run not heard begins with its round's first message
                return f"PFLG {VERSION} {run} 0\n".encode("ascii")
            written = self._begun(run, start, known)
            kept = start - 1
        elif prev > known:
            return f"PFLG {VERSION} {run} {known}\n".encode("ascii")
        else:
            kept = known
        said = self.said
        for seq, at_ms, level, lens, text in lines:
            if seq <= kept:
                continue  # sent again: kept already
            written.append(f"{_clock_text(at_ms)} {level} {lens} #{seq} {text}")
            kept = seq
            # The app's own warnings and errors; its system log's are a driver's.
            if level in "WE" and (lens == "-" or self.lens in (None, lens)):
                said = {"level": level, "lens": lens, "text": text}
                said |= {"at_ms": at_ms, "heard_ms": self.clock()}
        if written and self._write(written):
            self.run, self.kept, self.said = run, kept, said
        return f"PFLG {VERSION} {self.run} {self.kept}\n".encode("ascii")

    def _begun(self, run: str, start: int, known: int | None) -> list[str]:
        """The marks of ``run`` begun at ``start``: not heard before -- the app started
        again, or this recorder -- or the phone no longer keeping the lines after
        ``known``, the newest kept."""
        marks = []
        if known is not None:
            gone = start - known - 1
            marks.append(self._mark(f"{gone} lines no longer kept on the phone"))
        elif start > 1:
            marks.append(self._mark(f"lines 1 to {start - 1} were not heard"))
        when = _clock_text(self.clock())
        return [*marks, f"--- run {run} from line {start}, heard {when}"]

    def _mark(self, text: str) -> str:
        return f"--- {text}, {_clock_text(self.clock())}"

    def _write(self, lines: list[str]) -> bool:
        """``lines`` added to the file, a new file begun past KEEP_BYTES; False when
        they could not be written: not answered, sent again (FR-006)."""
        try:
            if self.path.exists() and self.path.stat().st_size > KEEP_BYTES:
                self.path.replace(self.path.with_name(FILE + ".1"))
                if not lines[0].startswith("--- run "):  # the new file says whose
                    lines = [f"--- run {self.run} from line {self.kept + 1}", *lines]
            with self.path.open("a", encoding="utf-8") as f:
                f.write("".join(f"{line}\n" for line in lines))
        except OSError:
            return False
        return True


def last_word(said: object, now_ms: int) -> str:
    """The phone's last warning or error a heartbeat holds, as a camera's line says it
    while the camera does not record; "" when there is none under SAID_MS old."""
    if not isinstance(said, dict):
        return ""
    heard, text = said.get("heard_ms"), said.get("text")
    if not isinstance(heard, int) or not isinstance(text, str) or not text:
        return ""
    return f"the phone: {text}" if 0 <= now_ms - heard <= SAID_MS else ""


def _read(
    message: bytes,
) -> tuple[str, int, int, list[tuple[int, int, str, str, str]]] | None:
    """A log message's run, the line its round began from, the line sent just before
    its first, and its lines; None for none."""
    if not message.startswith(TAG):
        return None
    try:
        head, *rest = message.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        return None
    parts = head.split(" ")
    if len(parts) != 5 or parts[1] != VERSION or not _RUN.fullmatch(parts[2]):
        return None
    if not (parts[3].isdigit() and parts[4].isdigit()) or int(parts[3]) < 1:
        return None
    lines = []
    for line in rest:
        found = _LINE.fullmatch(line)
        if found is None:
            continue
        seq, at_ms, level, lens, text = found.groups()
        lines.append((int(seq), int(at_ms), level, lens, text))
    return parts[2], int(parts[3]), int(parts[4]), lines


def _where(path: Path) -> tuple[str | None, int]:
    """The run and the newest line ``path`` holds, from its last lines back to the
    run's mark -- KEEP_BYTES of them at most: (None, 0) when it holds none, or cannot
    be read."""
    try:
        lines = path.read_bytes().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None, 0
    newest = None
    for line in reversed(lines):
        seq = _SEQ.match(line)
        if seq is not None and newest is None:
            newest = int(seq.group(1))
        mark = _MARK.match(line)
        if mark is not None:
            return mark.group(1), newest or int(mark.group(2)) - 1
    return None, 0


def _clock_text(ms: int) -> str:
    """``ms`` as this computer's local time, to the millisecond."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000)) + (
        f".{ms % 1000:03d}"
    )
