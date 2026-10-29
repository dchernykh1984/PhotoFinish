"""The referee's crossings: the output file, its state and its journal."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app import files, output_list
from app.lines import parse_time
from app.output_list import Change, OutputList

TAKEN = "15#20389 11:35:29.615#nextLap#"
RIDER = "\u0418\u0432\u0430\u043d"  # Cyrillic, as the older C++ tools wrote it


def ms(text: str) -> int:
    value = parse_time(text)
    assert value is not None
    return value


def take(out: OutputList, *texts: str) -> None:
    out.follow([*out.taken, *texts], list(texts), [])


def journal(out: OutputList) -> list[dict[str, Any]]:
    text = out.journal_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def without_at(entry: dict[str, Any]) -> dict[str, Any]:
    assert datetime.fromisoformat(entry["at"]).tzinfo is not None
    return {key: value for key, value in entry.items() if key != "at"}


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "out.txt"


def test_a_new_output_starts_empty_and_journals_nothing(path: Path) -> None:
    out = OutputList(path)
    assert path.read_bytes() == b""
    state = json.loads(out.state_path.read_text())
    assert (state["lines"], state["input_taken"]) == ([], [])
    assert not out.journal_path.exists()


def test_lines_keep_time_order_and_lines_without_a_time_come_last(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    take(out, "7##", "3#20389 11:35:20.000#nextLap#")
    assert out.add("9", ms("20389 11:35:29.615"), "finish", Change("frame")) == 2
    take(out, "8#bad#nextLap#")
    assert path.read_bytes().decode().splitlines() == [
        "3#20389 11:35:20.000#nextLap#",
        TAKEN,
        "9#20389 11:35:29.615#finish#",
        "7##",
        "8#bad#nextLap#",
    ]
    assert path.read_bytes().endswith(b"#\n")


def test_a_time_from_a_frame_moves_its_line_and_is_journaled(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    take(out, "16#20389 11:35:29.600#nextLap#")
    frames: list[list[Any]] = [["a.mkv", 54321, 1761716129587], ["a.mkv", 54322, 1]]
    offsets = {"camera_ms": 0, "source_ms": -12}
    change = Change("interpolated", "cam1", frames, 0.41, offsets)
    assert out.set_time(1, ms("20389 11:35:29.594"), change) == 0
    after = "15#20389 11:35:29.594#nextLap#"
    assert out.texts()[0] == after
    assert (out.lines[0].origin, out.lines[0].method) == (
        {"input": TAKEN},
        "interpolated",
    )
    assert without_at(journal(out)[-1]) == {
        "op": "time",
        "before": TAKEN,
        "after": after,
        "input": TAKEN,
        "camera": "cam1",
        "frames": frames,
        "method": "interpolated",
        "fraction": 0.41,
        "offsets": offsets,
    }


def test_a_line_without_a_time_field_gets_one(path: Path) -> None:
    out = OutputList(path)
    take(out, "7##")
    take(out, "8")
    out.set_time(0, ms("1 0:0:1"), Change("typed"))
    out.set_time(1, ms("1 0:0:2"), Change("typed"))
    assert out.texts() == ["7#1 0:0:1.000#", "8#1 0:0:2.000#"]


def test_a_number_changes_in_place_and_cannot_break_the_line(path: Path) -> None:
    assert output_list.clean_number(" 1#2\u20283\r\n") == "1 2 3"
    out = OutputList(path)
    take(out, TAKEN)
    assert out.set_number(0, " 5#1\n") == 0
    assert out.texts() == ["5 1#20389 11:35:29.615#nextLap#"]
    with pytest.raises(ValueError, match="number"):
        out.set_number(0, " # ")
    with pytest.raises(ValueError, match="number"):
        out.add("\n", 0, "finish", Change("typed"))
    assert [entry["op"] for entry in journal(out)] == ["take", "number"]
    assert journal(out)[-1]["method"] == "input"


def test_a_removed_line_leaves_the_file_and_stays_in_the_journal(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    out.add("9", ms("20389 11:35:30.000"), "finish", Change("hand"))
    out.remove(0)
    assert out.texts() == ["9#20389 11:35:30.000#finish#"]
    assert without_at(journal(out)[-1]) == {
        "op": "remove",
        "before": TAKEN,
        "input": TAKEN,
    }
    assert without_at(journal(out)[1]) == {
        "op": "add",
        "after": "9#20389 11:35:30.000#finish#",
        "method": "hand",
    }


def test_copy_to_output_applies_a_changed_input_line(path: Path) -> None:
    out = OutputList(path)
    take(out, "14#20389 11:35:29.550#nextLap#", TAKEN)
    out.follow(out.taken, [], [TAKEN])
    assert out.lines[1].removed_from_input
    current = "15#20389 11:35:29.500#nextLap#"
    assert out.copy_input(1, current) == 0
    assert out.taken[1] == current
    line = out.lines[0]
    assert (line.text, line.origin, line.removed_from_input) == (
        current,
        {"input": current},
        False,
    )
    assert without_at(journal(out)[-1]) == {
        "op": "copy",
        "before": TAKEN,
        "after": current,
        "input": current,
        "method": "input",
    }


def test_copy_to_output_brings_back_a_line_the_referee_removed(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    out.remove(0)
    current = "15#20389 11:35:29.500#nextLap#"
    assert out.copy_input(0, current) == 0
    assert out.lines[0].origin == {"input": current}
    assert without_at(journal(out)[-1]) == {
        "op": "copy",
        "after": current,
        "input": current,
        "method": "input",
    }


def test_of_twin_lines_copy_changes_the_one_the_referee_left(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN, TAKEN)
    out.set_time(0, ms("20389 11:35:29.700"), Change("frame"))
    out.copy_input(1, "15#20389 11:35:29.620#nextLap#")
    assert out.texts() == [
        "15#20389 11:35:29.620#nextLap#",
        "15#20389 11:35:29.700#nextLap#",
    ]


def test_the_list_comes_back_with_its_origins_and_marks(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN, TAKEN)
    out.add("9", ms("20389 11:35:30.000"), "finish", Change("hand"))
    out.follow([], [], [TAKEN, TAKEN, TAKEN, "never taken"])
    again = OutputList(path)
    assert (again.lines, again.taken) == (out.lines, [])
    assert [line.removed_from_input for line in again.lines] == [True, True, False]
    assert len(journal(again)) == 3


def test_an_outside_change_is_kept_and_the_list_written_again(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    assert not out.check_outside()
    path.write_text("edited by hand\n")
    assert out.check_outside()
    entry = journal(out)[-1]
    assert entry["op"] == "outside_change"
    assert (path.parent / entry["backup"]).read_text() == "edited by hand\n"
    assert path.read_text() == TAKEN + "\n"


def test_a_change_keeps_an_outside_version_first(path: Path) -> None:
    out = OutputList(path)
    path.write_text("x\n")
    take(out, TAKEN)
    entries = journal(out)
    assert [entry["op"] for entry in entries] == ["outside_change", "take"]
    assert (path.parent / entries[0]["backup"]).read_text() == "x\n"


def test_a_deleted_output_is_written_again(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    path.unlink()
    assert out.check_outside()
    assert "backup" not in journal(out)[-1]
    assert path.read_text() == TAKEN + "\n"


def test_crossings_in_a_chosen_file_start_the_list(path: Path) -> None:
    original = (
        b"\xef\xbb\xbf2#20389 11:35:30.000#finish#\r\n"
        + f"1#20389 11:35:29.000#{RIDER}#\r\n\r\n".encode("cp1251")
        + b"3##"
    )
    path.write_bytes(original)
    out = OutputList(path)
    assert out.texts() == [
        f"1#20389 11:35:29.000#{RIDER}#",
        "2#20389 11:35:30.000#finish#",
        "3##",
    ]
    assert {(line.method, line.origin["outside"]) for line in out.lines} == {
        ("outside", True)
    }
    entries = journal(out)
    assert [entry["op"] for entry in entries] == ["outside_change"]
    assert (path.parent / entries[0]["backup"]).read_bytes() == original
    assert path.read_text(encoding="utf-8").splitlines() == out.texts()
    OutputList(path)
    assert len(journal(out)) == 1


def test_a_state_that_cannot_be_read_is_kept_aside(path: Path) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    out.state_path.write_text("{not json")
    again = OutputList(path)
    assert again.lines[0].origin == {"outside": True}
    (broken,) = path.parent.glob("out.txt.state.json.broken-*")
    assert broken.read_text() == "{not json"


def test_after_a_crash_between_the_state_and_the_file_the_state_wins(
    path: Path,
) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    old = path.read_bytes()
    take(out, "16#20389 11:35:30.000#nextLap#")
    path.write_bytes(old)
    again = OutputList(path)
    assert path.read_text().splitlines() == again.texts() == out.texts()
    assert journal(again)[-1]["op"] == "outside_change"


def test_a_change_that_cannot_be_written_is_undone(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = OutputList(path)
    take(out, TAKEN)

    def full(_path: Path, _data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(output_list, "_write_in_one_step", full)
    with pytest.raises(OSError, match="disk full"):
        out.remove(0)
    with pytest.raises(OSError, match="disk full"):
        take(out, "16#20389 11:35:30.000#nextLap#")
    assert (out.texts(), out.taken) == ([TAKEN], [TAKEN])


def test_a_journal_line_cut_short_does_not_swallow_the_next(path: Path) -> None:
    out = OutputList(path)
    out.journal_path.write_text('{"op": "ta')
    take(out, TAKEN)
    assert json.loads(out.journal_path.read_text().splitlines()[-1])["op"] == "take"


def test_a_rename_refused_for_a_moment_is_tried_again(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Path.replace
    refused: list[Path] = []

    def replace(self: Path, target: Path) -> Path:
        if not refused:
            refused.append(self)
            raise PermissionError("in use")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(files.time, "sleep", lambda _seconds: None)
    OutputList(path)
    assert refused
    assert path.read_bytes() == b""


def test_a_rename_refused_for_good_fails(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, target: Path) -> Path:
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "replace", refuse)
    monkeypatch.setattr(files.time, "sleep", lambda _seconds: None)
    with pytest.raises(PermissionError):
        OutputList(path)


def test_a_change_the_output_refuses_leaves_state_and_journal_as_they_were(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    state, entries = out.state_path.read_bytes(), len(journal(out))
    real = output_list._write_in_one_step

    def locked(target: Path, data: bytes) -> None:
        if target == path:
            raise PermissionError("held by the protocol generator")
        real(target, data)

    monkeypatch.setattr(output_list, "_write_in_one_step", locked)
    for _ in range(3):  # the input followed at every poll while it is held
        with pytest.raises(PermissionError):
            take(out, "16#20389 11:35:30.000#nextLap#")
    assert out.state_path.read_bytes() == state
    assert len(journal(out)) == entries
    assert out.texts() == [TAKEN]
    monkeypatch.setattr(output_list, "_write_in_one_step", real)
    take(out, "16#20389 11:35:30.000#nextLap#")
    assert [e["op"] for e in journal(out)[entries:]] == ["take"]
    assert OutputList(path).texts() == out.texts()


def test_a_journal_that_refuses_a_change_written_is_an_error(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = OutputList(path)

    def full(target: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(output_list, "_append", full)
    with pytest.raises(output_list.JournalError, match="disk full"):
        take(out, TAKEN)
    assert path.read_text() == TAKEN + "\n"  # the change is written


def test_a_long_race_is_listed_without_a_wait(path: Path) -> None:
    import time

    texts = [
        f"{n}#0 {n // 3600}:{n // 60 % 60}:{n % 60}.000#finish#" for n in range(3000)
    ]
    path.write_text("\n".join([*texts, "7##"]) + "\n")
    started = time.perf_counter()
    out = OutputList(path)
    take(
        out,
        *(
            f"{n}#0 {n // 3600}:{n // 60 % 60}:{n % 60}.500#nextLap#"
            for n in range(500)
        ),
    )
    assert time.perf_counter() - started < 5.0
    assert out.texts()[0] == texts[0]
    assert out.texts()[1].startswith("0#0 0:0:0.500")
    assert out.texts()[-1] == "7##"


def test_after_a_broken_state_the_journal_says_what_was_taken(path: Path) -> None:
    out = OutputList(path)
    second = "16#20389 11:35:30.000#nextLap#"
    take(out, TAKEN, second)
    out.set_time(0, ms("20389 11:35:29.500"), Change("frame"))  # the referee's fix
    changed = "16#20389 11:35:30.100#nextLap#"
    out.copy_input(1, changed)
    with out.journal_path.open("a") as f:
        f.write("not json\n[1]\n")
    out.state_path.write_text("{broken")
    again = OutputList(path)
    assert again.taken == [TAKEN, changed]
    from app.input_follow import align

    found = align(again.taken, [TAKEN, changed])  # the chronometer's file as it is
    assert found.new == []  # nothing taken twice, the corrected line not either


def test_an_output_as_written_is_not_read_again_at_each_poll(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = OutputList(path)
    take(out, TAKEN)
    reads: list[Path] = []
    real = output_list._read

    def counted(target: Path) -> bytes | None:
        reads.append(target)
        return real(target)

    monkeypatch.setattr(output_list, "_read", counted)
    for _ in range(3):
        assert not out.check_outside()
    assert reads == []
    os.utime(path, ns=(1, 1))  # touched, not changed: read once, then not again
    assert not out.check_outside()
    assert not out.check_outside()
    assert reads == [path]
    path.write_text("edited\n")
    assert out.check_outside()


def test_a_line_whose_time_stays_keeps_its_place_among_its_ties(path: Path) -> None:
    out = OutputList(path)
    first, second = "12#0 1:0:0.000#finish#", "7#0 1:0:0.000#finish#"
    take(out, first, second, "9#0 1:0:5.000#finish#")
    assert out.set_number(0, "21") == 0  # the typo fixed: the placing stays
    assert out.texts()[:2] == ["21#0 1:0:0.000#finish#", second]
    assert out.set_time(0, ms("0 1:0:0.000"), Change("typed")) == 0
    assert out.texts()[0] == "21#0 1:0:0.000#finish#"
    assert out.set_time(0, ms("0 1:0:6.000"), Change("typed")) == 2  # a new time moves


def test_a_journal_held_a_moment_is_written_after_all(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = OutputList(path)
    real = Path.open
    held: list[bool] = [True]

    def opening(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == out.journal_path and held:
            held.pop()
            raise PermissionError("held")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opening)
    monkeypatch.setattr(files.time, "sleep", lambda seconds: None)
    take(out, TAKEN)
    assert [e["op"] for e in journal(out)] == ["take"]
