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
RUNS_KEPT = 4  # the runs a recorder goes on with: phones given one code, apps restarted
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
        # The newest line kept of each run lately heard, the newest run last: two
        # phones given one code each go on where they were, not again from the start;
        # and the run written last, whose lines the file goes on with. A recorder
        # started again finds both in its file.
        self.run, self.runs = _where(self.path)
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
        known = self.runs.get(run)
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
            said = self._word(said, level, lens, text, at_ms)
        before = start - 1 if known is None else known
        if written and self._write(written, run, before):
            self.run, self.said = run, said
            self.runs.pop(run, None)
            self.runs[run] = kept
            while len(self.runs) > RUNS_KEPT:
                del self.runs[next(iter(self.runs))]
        return f"PFLG {VERSION} {run} {self.runs.get(run, 0)}\n".encode("ascii")

    def _word(
        self, said: dict[str, Any], level: str, lens: str, text: str, at_ms: int
    ) -> dict[str, Any]:
        """The phone's last word after a line: the app's own newest of this lens or of
        the phone, when it is a warning or an error; a line after it -- streaming
        again -- says it is over. The system log's lines are a driver's, not why."""
        mine = lens == "-" or self.lens in (None, lens)
        if level not in "IWE" or not mine:
            return said
        if level == "I":
            return {}
        heard = {"text": text, "at_ms": at_ms, "heard_ms": self.clock()}
        return {"level": level, "lens": lens, **heard}

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

    def _write(self, lines: list[str], run: str, kept: int) -> bool:
        """``lines`` of ``run`` added to the file, ``kept`` its newest line before them;
        a new file begun past KEEP_BYTES, saying whose lines follow; False when they
        could not be written: not answered, sent again (FR-006)."""
        try:
            rotate = self.path.exists() and self.path.stat().st_size > KEEP_BYTES
            if rotate:
                self.path.replace(self.path.with_name(FILE + ".1"))
            # Each line is the run's whose mark is the last before it: another run's
            # lines -- a second phone given the code -- begin with theirs.
            if (rotate or run != self.run) and not any(
                line.startswith("--- run ") for line in lines
            ):
                lines = [f"--- run {run} from line {kept + 1}", *lines]
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


def _where(path: Path) -> tuple[str | None, dict[str, int]]:
    """The run ``path`` was written last with, and the newest line it holds of each of
    its last runs, each line the run's whose mark is the last before it -- KEEP_BYTES
    of them at most; (None, {}) when it holds none, or cannot be read."""
    try:
        lines = path.read_bytes().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None, {}
    run: str | None = None
    runs: dict[str, int] = {}
    for line in lines:
        mark = _MARK.match(line)
        if mark is not None:
            run = mark.group(1)
            runs[run] = max(runs.pop(run, 0), int(mark.group(2)) - 1)
        elif (seq := _SEQ.match(line)) is not None and run is not None:
            runs[run] = int(seq.group(1))
    return run, dict(list(runs.items())[-RUNS_KEPT:])


def _clock_text(ms: int) -> str:
    """``ms`` as this computer's local time, to the millisecond; as it came when no
    time of this computer's is so far -- a phone's clock gone wrong: its line kept all
    the same, or none after it would be."""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000)) + (
            f".{ms % 1000:03d}"
        )
    except OverflowError, OSError, ValueError:
        return f"{ms} ms"
