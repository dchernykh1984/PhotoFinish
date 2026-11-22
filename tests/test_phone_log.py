"""The phone's log, kept beside its camera's recording (specs/008-phone-log)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.recorder import phone_log
from app.recorder.phone_log import PhoneLog, last_word

RUN = "0123456789abcdef"
LATER = "fedcba9876543210"  # the app started again
START = 1_794_918_339_000


def message(
    start: int,
    *lines: tuple[int, str, str, str],
    run: str = RUN,
    prev: int | None = None,
) -> bytes:
    """A message of ``run``'s lines, its round begun at ``start``: (seq, level, lens,
    text) each; ``prev`` the line sent before its first, ``start - 1`` for the round's
    first message."""
    body = "".join(
        f"{seq} {START + seq} {lvl} {lens} {text}\n" for seq, lvl, lens, text in lines
    )
    before = start - 1 if prev is None else prev
    return f"PFLG 1 {run} {start} {before}\n{body}".encode()


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
    lost = message(4, (6, "I", "-", "six"), prev=5)
    assert log.heard(lost) == f"PFLG 1 {RUN} 3\n".encode()
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
        "--- 3 lines no longer kept on the phone",
        f"--- run {RUN} from line 5",
        "W - #5 five",
    ]


def test_gaps_between_a_message_s_lines_are_lines_the_phone_let_go_of(
    log: PhoneLog, tmp_path: Path
) -> None:
    # A full phone lets its system log's oldest lines go from between the app's own.
    assert (
        log.heard(
            message(
                1, (1, "I", "-", "start"), (3, "E", "-", "error"), (4, "I", "-", "on")
            )
        )
        == f"PFLG 1 {RUN} 4\n".encode()
    )
    later = message(1, (6, "I", "-", "six"), prev=4)  # a round's second, after a gap
    assert log.heard(later) == f"PFLG 1 {RUN} 6\n".encode()
    assert [line for line in kept(tmp_path) if "#" in line] == [
        "I - #1 start",
        "E - #3 error",
        "I - #4 on",
        "I - #6 six",
    ]


def test_a_run_not_heard_begins_with_its_round_s_first_message(
    log: PhoneLog, tmp_path: Path
) -> None:
    # The round's first was lost: its second cannot begin the run -- lines before it
    # would never come -- and the phone sends the round again.
    second = message(1, (4, "I", "-", "four"), prev=3)
    assert log.heard(second) == f"PFLG 1 {RUN} 0\n".encode()
    assert not (tmp_path / phone_log.FILE).exists()


def test_the_app_started_again_is_a_run_of_its_own(
    log: PhoneLog, tmp_path: Path
) -> None:
    log.heard(message(1, (1, "I", "-", "one"), (2, "I", "-", "two")))
    assert log.heard(message(1, (1, "I", "-", "again"), run=LATER)) == (
        f"PFLG 1 {LATER} 1\n".encode()
    )
    assert kept(tmp_path)[-2:] == [f"--- run {LATER} from line 1", "I - #1 again"]


def test_two_phones_given_one_code_each_go_on_where_they_were(
    log: PhoneLog, tmp_path: Path
) -> None:
    for n in (1, 2):
        assert log.heard(message(n, (n, "I", "-", f"one {n}"))) == (
            f"PFLG 1 {RUN} {n}\n".encode()
        )
        assert log.heard(message(n, (n, "I", "-", f"other {n}"), run=LATER)) == (
            f"PFLG 1 {LATER} {n}\n".encode()
        )
    log.heard(message(1, (1, "I", "-", "one 1"), (2, "I", "-", "one 2")))  # again
    lines = [line for line in kept(tmp_path) if "#" in line]
    assert lines == ["I - #1 one 1", "I - #1 other 1", "I - #2 one 2", "I - #2 other 2"]


def test_two_phones_given_one_code_go_on_where_they_were_after_a_restart_too(
    log: PhoneLog, tmp_path: Path
) -> None:
    # Their lines in turns: each turn begins with its run's mark, so a recorder
    # started again knows whose each line is.
    log.heard(message(1, (1, "I", "-", "one 1")))
    log.heard(message(1, (1, "I", "-", "other 1"), run=LATER))
    log.heard(message(2, (2, "I", "-", "one 2"), (3, "I", "-", "one 3")))
    again = PhoneLog(tmp_path)
    assert again.runs == {LATER: 1, RUN: 3}
    assert again.heard(message(2, (2, "I", "-", "other 2"), run=LATER)) == (
        f"PFLG 1 {LATER} 2\n".encode()
    )
    assert [line for line in kept(tmp_path) if "other" in line][-1] == "I - #2 other 2"


def test_a_recorder_reads_its_file_at_the_first_message_not_at_its_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file of 10 MB read before the recorder's first frame would hold it back.
    found: list[Path] = []
    real = phone_log._where

    def where(path: Path) -> tuple[str | None, dict[str, int]]:
        found.append(path)
        return real(path)

    monkeypatch.setattr(phone_log, "_where", where)
    log = PhoneLog(tmp_path)
    assert found == []
    log.heard(message(1, (1, "I", "-", "one")))
    log.heard(message(2, (2, "I", "-", "two")))
    assert found == [tmp_path / phone_log.FILE]  # once


def test_a_recorder_started_again_goes_on_where_its_file_is(tmp_path: Path) -> None:
    PhoneLog(tmp_path).heard(message(1, (1, "I", "-", "one"), (2, "I", "-", "two")))
    again = PhoneLog(tmp_path)
    assert (again.run, again.runs) == (RUN, {RUN: 2})
    assert again.heard(message(2, (2, "I", "-", "two"), (3, "I", "-", "three"))) == (
        f"PFLG 1 {RUN} 3\n".encode()
    )
    assert [line for line in kept(tmp_path) if "#2" in line] == ["I - #2 two"]
    fresh = PhoneLog(tmp_path / "none")
    assert (fresh.run, fresh.runs) == (None, {})


def test_a_recorder_started_again_finds_its_run_far_back_in_its_file(
    tmp_path: Path,
) -> None:
    # On the emulator: a run's mark 120 kB back, a recorder killed and started again.
    log = PhoneLog(tmp_path)
    log.heard(message(1, (1, "I", "-", "PhotoFinish Camera 0.8.0")))
    for n in range(2, 1_002):
        log.heard(message(n, (n, "w", "-", "mapper: unsupported metadata " + "x" * 80)))
    again = PhoneLog(tmp_path)
    assert (again.run, again.runs) == (RUN, {RUN: 1_001})
    again.heard(message(1_002, (1_002, "W", "main", "connection lost")))
    assert "were not heard" not in (tmp_path / phone_log.FILE).read_text()


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
        b"PFLG 1 0123456789abcdef 0 0\n",
        b"PFLG 1 0123456789abcdef 1 x\n",
        b"PFLG 1 0123456789abcdef 1\n\xff\xfe",
    ],
)
def test_what_is_no_log_message_gets_no_answer(log: PhoneLog, datagram: bytes) -> None:
    assert log.heard(datagram) is None


def test_the_system_log_s_lines_are_kept_as_they_came(
    log: PhoneLog, tmp_path: Path
) -> None:
    log.heard(message(1, (1, "w", "-", "HWUI: Unknown dataspace 0")))
    assert kept(tmp_path)[-1] == "w - #1 HWUI: Unknown dataspace 0"
    again = PhoneLog(tmp_path)  # a recorder started again finds them too
    assert again.runs == {RUN: 1}


def test_a_word_from_the_phone_s_backlog_is_said_as_old_as_it_is(
    tmp_path: Path,
) -> None:
    # The recorder down for 40 minutes: the phone sends what it kept, an error of
    # then among it -- by the phone's own clock, whatever this computer's says.
    log = PhoneLog(tmp_path, clock=lambda: 5_000)  # this computer's clock: far off
    then, now = START, START + 40 * 60_000
    backlog = f"PFLG 1 {RUN} 1 0\n1 {then} E - camera error 4\n2 {now} I - connecting\n"
    log.heard(backlog.encode())
    assert last_word(log.said, 5_000) == "the phone, 40 min ago: camera error 4"
    assert (
        last_word(log.said, 5_000 + 60_000) == "the phone, 41 min ago: camera error 4"
    )


def test_a_line_whose_time_is_no_time_here_is_kept_all_the_same(
    log: PhoneLog, tmp_path: Path
) -> None:
    far = (
        b"PFLG 1 " + RUN.encode() + b" 1 0\n1 99999999999999999999 E - camera error 4\n"
    )
    assert log.heard(far) == f"PFLG 1 {RUN} 1\n".encode()
    assert (tmp_path / phone_log.FILE).read_text().splitlines()[-1] == (
        "99999999999999999999 ms E - #1 camera error 4"
    )


def test_a_line_holding_another_break_is_one_line_at_a_restart(tmp_path: Path) -> None:
    # A driver's line may hold a form feed or a line separator: written as one line,
    # read back as one -- its tail must not pass for a mark of another run.
    log = PhoneLog(tmp_path)
    tail = f"\u2028--- run {LATER} from line 9"
    log.heard(message(1, (1, "w", "-", "driver: one" + tail)))
    again = PhoneLog(tmp_path)
    assert again.runs == {RUN: 1}


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
            (1, "I", "-", "the camera gives frames"),  # no warning
            (2, "E", "-", "camera error 4"),
            (3, "W", "main", "connection lost"),  # another lens's
            (4, "e", "-", "mapper: unsupported metadata"),  # the system log's
        )
    )
    assert log.said == {
        "level": "E",
        "lens": "-",
        "text": "camera error 4",
        "at_ms": START + 2,
        "run": RUN,
        "phone_ms": START + 4,  # the newest line the phone sent with it
        "heard_ms": START + 10_000,
    }
    assert last_word(log.said, START + 10_000 + phone_log.SAID_MS - 3) == (
        "the phone: camera error 4"
    )
    # A failure said once goes on: still shown, with how long ago it was said.
    assert last_word(log.said, START + 10_000 + 5 * phone_log.SAID_MS) == (
        "the phone, 5 min ago: camera error 4"
    )
    assert last_word({}, START) == ""
    assert last_word("x", START) == ""
    reopened = (
        5,
        "I",
        "-",
        "camera 0: main at 2560x1440, 60 fps",
    )  # the camera's retry
    log.heard(message(5, reopened))
    assert log.said["text"] == "camera error 4"  # a retry's own line: no failure over
    log.heard(message(6, (6, "W", "-", "connection lost: refused; connecting again")))
    assert log.said["text"] == "connection lost: refused; connecting again"
    (tmp_path / "one").mkdir()
    one_lens = PhoneLog(tmp_path / "one")  # a phone of one camera: any lens's
    one_lens.heard(message(1, (1, "W", "main", "connection lost")))
    assert one_lens.said["text"] == "connection lost"


def test_lines_that_cannot_be_written_are_not_answered_and_cost_nothing(
    tmp_path: Path,
) -> None:
    (tmp_path / phone_log.FILE).mkdir()  # a folder where the file would be
    log = PhoneLog(tmp_path)
    assert (
        log.heard(message(1, (1, "E", "-", "camera error 4")))
        == f"PFLG 1 {RUN} 0\n".encode()
    )
    assert log.said == {}


def test_a_new_file_begun_for_a_new_run_says_that_run_s(
    log: PhoneLog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phone_log, "KEEP_BYTES", 100)
    log.heard(message(1, *[(n, "I", "-", "x" * 40) for n in range(1, 4)]))
    log.heard(message(5, (5, "I", "-", "five"), run=LATER))  # its first lines not heard
    assert kept(tmp_path) == [
        "--- lines 1 to 4 were not heard",
        f"--- run {LATER} from line 5",
        "I - #5 five",
    ]


def test_a_long_file_is_kept_aside_and_a_new_one_says_whose(
    log: PhoneLog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phone_log, "KEEP_BYTES", 100)
    log.heard(message(1, *[(n, "I", "-", "x" * 40) for n in range(1, 4)]))
    log.heard(message(4, (4, "I", "-", "four")))
    assert (tmp_path / "phone.log.1").exists()
    assert kept(tmp_path) == [f"--- run {RUN} from line 4", "I - #4 four"]


def test_the_phones_last_word_is_said_whatever_number_its_times_are_written_as() -> (
    None
):
    # A heartbeat written by another version, its times floats or strings: the
    # phone's warning said all the same, never hidden; a time that is none, nothing.
    from app.recorder.phone_log import last_word

    times = {"at_ms": 1000, "phone_ms": 1000, "heard_ms": 5000}
    said: dict[str, object] = {"text": "camera error 4", **times}
    for written in (float, str):
        word = {**said, **{k: written(v) for k, v in times.items()}}
        assert last_word(word, 5_000) == "the phone: camera error 4"
    assert last_word({**said, "at_ms": "soon"}, 5_000) == ""
    assert last_word({**said, "at_ms": float("inf")}, 5_000) == ""


APP = "PhotoFinish Camera {} on Xiaomi 25113PN0EC, Android 16 (API 36)"


def test_the_app_s_last_start_is_read_from_the_phone_s_log(
    log: PhoneLog, tmp_path: Path
) -> None:
    # FR-001: each start of the app logs its version, phone and Android first; the
    # newest the log holds is the app at work, whatever was said after it.
    assert phone_log.started(tmp_path) == ""  # no log yet
    log.heard(message(1, (1, "I", "-", APP.format("0.12.0")), (2, "W", "main", "x")))
    assert phone_log.started(tmp_path) == APP.format("0.12.0")
    started_again = message(
        1, (1, "I", "-", APP.format("0.13.1")), (2, "I", "-", "main"), run=LATER
    )
    log.heard(started_again)
    assert phone_log.started(tmp_path) == APP.format("0.13.1")


def test_no_line_but_the_app_s_own_start_is_taken_for_it(
    log: PhoneLog, tmp_path: Path
) -> None:
    # What came over the network as a lens's line, a warning, the system log's, or
    # a start quoted: no version of the app's -- nor one longer than a version is.
    for seq, (level, lens, text) in enumerate(
        (
            ("I", "main", APP.format("9.9.9")),
            ("W", "-", APP.format("9.9.9")),
            ("w", "-", APP.format("9.9.9")),
            ("I", "-", "said: " + APP.format("9.9.9")),
            ("I", "-", APP.format("9" * 41)),
            ("I", "-", APP.format("9.9.9") + "x" * 200),
        ),
        start=1,
    ):
        log.heard(message(1, (seq, level, lens, text), prev=seq - 1))
    assert len(kept(tmp_path)) == 7  # each kept, after the run's mark
    assert phone_log.started(tmp_path) == ""


def test_the_app_s_start_is_read_from_the_file_kept_before_a_new_one_began(
    tmp_path: Path,
) -> None:
    # KEEP_BYTES past, the log goes on in a new file: its run's start in the one
    # kept before -- or a phone's clock gone wrong, its time kept as it came.
    before = f"--- run {RUN} from line 1\n1794918339001 ms I - #1 {APP.format('1.0')}\n"
    (tmp_path / (phone_log.FILE + ".1")).write_text(before, encoding="utf-8")
    after = f"--- run {RUN} from line 90000\n2026-11-22 12:00:00.000 I main #90000 x\n"
    (tmp_path / phone_log.FILE).write_text(after, encoding="utf-8")
    assert phone_log.started(tmp_path) == APP.format("1.0")


def test_the_app_s_start_is_read_whole_from_a_log_written_with_windows_line_ends(
    tmp_path: Path,
) -> None:
    # The log is written as text: Windows ends each of its lines with "\r\n", and
    # the app's start is said without the "\r".
    said = APP.format("0.13.1")
    lines = [f"--- run {RUN} from line 1", f"2026-11-22 10:15:03.123 I - #1 {said}"]
    (tmp_path / phone_log.FILE).write_bytes("\r\n".join(lines).encode() + b"\r\n")
    assert phone_log.started(tmp_path) == said
