"""The phone's log, kept beside its camera's recording (specs/008-phone-log)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.recorder import phone_log
from app.recorder.phone_log import PhoneLog, last_word

RUN = "0123456789abcdef"
LATER = "fedcba9876543210"  # the app started again
START = 1_794_918_339_000


def message(start: int, *lines: tuple[int, str, str, str], run: str = RUN) -> bytes:
    """A message of ``run``'s lines from ``start``: (seq, level, lens, text) each."""
    body = "".join(
        f"{seq} {START + seq} {lvl} {lens} {text}\n" for seq, lvl, lens, text in lines
    )
    return f"PFLG 1 {run} {start}\n{body}".encode()


def kept(folder: Path) -> list[str]:
    """The file's lines, each its level, lens, number and text -- or a mark."""
    found = []
    for line in (folder / phone_log.FILE).read_text(encoding="utf-8").splitlines():
        found.append(line.split(", ")[0] if line.startswith("---") else line[24:])
    return found


@pytest.fixture
def log(tmp_path: Path) -> PhoneLog:
    return PhoneLog(tmp_path, "main", clock=lambda: START + 10_000)


def test_lines_are_kept_in_the_phone_s_order_and_answered(
    log: PhoneLog, tmp_path: Path
) -> None:
    answer = log.heard(
        message(
            1,
            (1, "I", "-", "PhotoFinish Camera 0.8.0"),
            (2, "E", "main", "camera error 4"),
        )
    )
    assert answer == f"PFLG 1 {RUN} 2\n".encode()
    assert kept(tmp_path) == [
        f"--- run {RUN} from line 1",
        "I - #1 PhotoFinish Camera 0.8.0",
        "E main #2 camera error 4",
    ]
    text = (tmp_path / phone_log.FILE).read_text(encoding="utf-8").splitlines()[1]
    assert text.startswith("20") and text[19] == "."  # the phone's time, to the ms


def test_a_line_sent_again_is_kept_once_and_one_after_a_lost_message_waits(
    log: PhoneLog, tmp_path: Path
) -> None:
    log.heard(message(1, (1, "I", "-", "one"), (2, "I", "-", "two")))
    assert log.heard(message(1, (2, "I", "-", "two"), (3, "I", "-", "three"))) == (
        f"PFLG 1 {RUN} 3\n".encode()
    )
    # A round's second message, its first lost on the way: not kept, sent again.
    assert log.heard(message(4, (6, "I", "-", "six"))) == f"PFLG 1 {RUN} 3\n".encode()
    assert [line for line in kept(tmp_path) if "#" in line] == [
        "I - #1 one",
        "I - #2 two",
        "I - #3 three",
    ]


def test_lines_the_phone_could_no_longer_keep_are_said_lost(
    log: PhoneLog, tmp_path: Path
) -> None:
    log.heard(message(1, (1, "I", "-", "one")))
    assert log.heard(message(5, (5, "W", "-", "five"))) == f"PFLG 1 {RUN} 5\n".encode()
    assert kept(tmp_path)[-3:] == [
        "--- 3 lines lost on the phone",
        f"--- run {RUN} from line 5",
        "W - #5 five",
    ]


def test_the_app_started_again_is_a_run_of_its_own(
    log: PhoneLog, tmp_path: Path
) -> None:
    log.heard(message(1, (1, "I", "-", "one"), (2, "I", "-", "two")))
    assert log.heard(message(1, (1, "I", "-", "again"), run=LATER)) == (
        f"PFLG 1 {LATER} 1\n".encode()
    )
    assert kept(tmp_path)[-2:] == [f"--- run {LATER} from line 1", "I - #1 again"]


def test_a_recorder_started_again_goes_on_where_its_file_is(tmp_path: Path) -> None:
    PhoneLog(tmp_path).heard(message(1, (1, "I", "-", "one"), (2, "I", "-", "two")))
    again = PhoneLog(tmp_path)
    assert (again.run, again.kept) == (RUN, 2)
    assert again.heard(message(2, (2, "I", "-", "two"), (3, "I", "-", "three"))) == (
        f"PFLG 1 {RUN} 3\n".encode()
    )
    assert [line for line in kept(tmp_path) if "#2" in line] == ["I - #2 two"]
    fresh = PhoneLog(tmp_path / "none")
    assert (fresh.run, fresh.kept) == (None, 0)


def test_a_run_first_heard_late_says_what_was_not_heard(
    log: PhoneLog, tmp_path: Path
) -> None:
    log.heard(message(7, (7, "I", "-", "seven")))
    assert kept(tmp_path)[:2] == [
        "--- lines 1 to 6 were not heard",
        f"--- run {RUN} from line 7",
    ]


@pytest.mark.parametrize(
    "datagram",
    [
        b"PFTS\x01" + bytes(8),  # a clock exchange
        b"PFLG 1 0123456789abcdef\n",  # no line it begins from
        b"PFLG 2 0123456789abcdef 1\n",
        b"PFLG 1 xyz 1\n",
        b"PFLG 1 0123456789abcdef 0\n",
        b"PFLG 1 0123456789abcdef 1\n\xff\xfe",
    ],
)
def test_what_is_no_log_message_gets_no_answer(log: PhoneLog, datagram: bytes) -> None:
    assert log.heard(datagram) is None


def test_a_line_that_cannot_be_read_is_passed_over(
    log: PhoneLog, tmp_path: Path
) -> None:
    raw = message(1, (1, "I", "-", "one")) + b"garbled\n2 x I - two\n"
    assert log.heard(raw) == f"PFLG 1 {RUN} 1\n".encode()


def test_the_last_warning_or_error_of_the_camera_s_lens_or_the_phone_is_its_word(
    tmp_path: Path,
) -> None:
    log = PhoneLog(tmp_path, "telephoto", clock=lambda: START + 10_000)
    log.heard(
        message(
            1,
            (1, "E", "-", "camera error 4"),
            (2, "W", "main", "connection lost"),  # another lens's
            (3, "I", "-", "the camera gives frames"),  # no warning
        )
    )
    assert log.said == {
        "level": "E",
        "lens": "-",
        "text": "camera error 4",
        "at_ms": START + 1,
        "heard_ms": START + 10_000,
    }
    assert last_word(log.said, START + 10_000 + phone_log.SAID_MS) == (
        "the phone: camera error 4"
    )
    assert last_word(log.said, START + 10_001 + phone_log.SAID_MS) == ""  # old
    assert last_word({}, START) == ""
    assert last_word("x", START) == ""
    (tmp_path / "one").mkdir()
    one_lens = PhoneLog(tmp_path / "one")  # a phone of one camera: any lens's
    one_lens.heard(message(1, (1, "W", "main", "connection lost")))
    assert one_lens.said["text"] == "connection lost"


def test_lines_that_cannot_be_written_are_not_answered_and_cost_nothing(
    tmp_path: Path,
) -> None:
    (tmp_path / phone_log.FILE).mkdir()  # a folder where the file would be
    log = PhoneLog(tmp_path)
    assert log.heard(message(1, (1, "E", "-", "camera error 4"))) == b"PFLG 1 None 0\n"
    assert log.said == {}


def test_a_long_file_is_kept_aside_and_a_new_one_says_whose(
    log: PhoneLog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phone_log, "KEEP_BYTES", 100)
    log.heard(message(1, *[(n, "I", "-", "x" * 40) for n in range(1, 4)]))
    log.heard(message(4, (4, "I", "-", "four")))
    assert (tmp_path / "phone.log.1").exists()
    assert kept(tmp_path) == [f"--- run {RUN} from line 4", "I - #4 four"]
