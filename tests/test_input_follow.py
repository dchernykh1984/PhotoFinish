"""The chronometer's file followed into the output list (US3)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import input_follow, output_list
from app.input_follow import InputFollow, InputLine, align
from app.output_list import OutputList

A = "1#20389 11:35:20.000#nextLap#"
B = "2#20389 11:35:21.000#nextLap#"
C = "3#20389 11:35:22.000#nextLap#"
D = "4#20389 11:35:23.000#nextLap#"


def test_appended_lines_are_new() -> None:
    result = align([A], [A, B])
    assert (result.taken, result.new, result.gone) == ([A, B], [B], [])


def test_an_edited_line_keeps_what_was_taken() -> None:
    edited = "2#20389 11:35:21.500#nextLap#"
    renumbered = "7#20389 11:35:22.000#nextLap#"
    result = align([A, B, C], [A, edited, renumbered])
    assert (result.taken, result.new, result.gone) == ([A, B, C], [], [])
    assert result.shown == [
        InputLine(A),
        InputLine(edited, B),
        InputLine(renumbered, C),
    ]


def test_a_line_gone_and_a_crossing_changed_beyond_recognition() -> None:
    other = "9#20389 11:35:29.000#finish#"
    result = align([A, B, C], [A, other, D])
    assert result.gone == [B, C]
    assert result.new == [other, D]
    assert result.taken == [A, other, D]


def test_a_line_inserted_before_an_edit_is_new_and_the_edit_held_back() -> None:
    edited = "2#20389 11:35:21.500#nextLap#"
    late = "8#20389 11:35:20.500#nextLap#"
    result = align([A, B, C], [A, late, edited, C])
    assert (result.new, result.gone) == ([late], [])
    assert result.taken == [A, late, B, C]
    assert result.shown[2] == InputLine(edited, B)


def test_a_file_with_nothing_in_common_is_a_new_competition() -> None:
    again = "1#20390 10:00:00.000#nextLap#"
    result = align([A, B], [again])
    assert (result.taken, result.new, result.gone) == ([again], [again], [A, B])
    assert align([A, B], []).gone == [A, B]


def test_twin_lines_are_two_crossings() -> None:
    result = align([A, A], [A, A, A])
    assert (result.taken, result.new) == ([A, A, A], [A])


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "results.txt", tmp_path / "out.txt"


def follow(files: tuple[Path, Path]) -> InputFollow:
    source, out = files
    return InputFollow(source, OutputList(out))


_SECONDS = iter(range(1_700_000_000, 1_800_000_000))


def write(path: Path, *lines: str, tail: str = "") -> None:
    """The file, its time a second later than the last: a rewrite keeping the size
    is seen on any file system, however coarse its clock."""
    path.write_text("".join(f"{line}\n" for line in lines) + tail, encoding="utf-8")
    ns = next(_SECONDS) * 1_000_000_000
    os.utime(path, ns=(ns, ns))


def test_new_lines_arrive_and_a_changed_one_waits_for_copy(
    files: tuple[Path, Path],
) -> None:
    source, out = files
    write(source, A, B, C)
    f = follow(files)
    assert f.poll()
    assert f.output.texts() == [A, B, C]
    write(source, A, B, C, D)
    assert f.poll()
    assert f.output.texts() == [A, B, C, D]
    edited = "2#20389 11:35:21.500#nextLap#"
    write(source, A, edited, C, D)
    assert f.poll()
    assert f.output.texts() == [A, B, C, D]
    assert f.lines[1] == InputLine(edited, B)
    assert f.copy(1) == 1
    assert f.output.texts() == [A, edited, C, D]
    assert f.lines[1] == InputLine(edited)
    assert out.read_text().splitlines() == [A, edited, C, D]
    entry = json.loads(f.output.journal_path.read_text().splitlines()[-1])
    assert (entry["op"], entry["before"], entry["after"]) == ("copy", B, edited)
    with pytest.raises(ValueError, match="as it was taken"):
        f.copy(1)


def test_the_input_is_only_read(files: tuple[Path, Path]) -> None:
    source, _ = files
    write(source, A, B)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    f = follow(files)
    f.poll()
    f.output.set_number(0, "11")
    f.output.remove(1)
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_a_line_still_being_written_waits_for_its_line_break(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _ = files
    write(source, A, tail="2#20389 11:3")
    written = source.stat().st_mtime_ns
    monkeypatch.setattr(input_follow.time, "time_ns", lambda: written + 100_000_000)
    f = follow(files)
    f.poll()
    assert f.output.texts() == [A]
    write(source, A, B)
    f.poll()
    assert f.output.texts() == [A, B]


def test_an_unchanged_or_missing_input_is_not_read_again(
    files: tuple[Path, Path],
) -> None:
    source, _ = files
    f = follow(files)
    assert not f.poll()
    write(source, A)
    assert f.poll()
    assert not f.poll()
    source.unlink()
    assert not f.poll()
    assert not f.output.lines[0].removed_from_input


def test_a_gone_line_is_marked_and_cleared_when_it_comes_back(
    files: tuple[Path, Path],
) -> None:
    source, _ = files
    write(source, A, B, C)
    f = follow(files)
    f.poll()
    write(source, A)
    f.poll()
    assert [line.removed_from_input for line in f.output.lines] == [False, True, True]
    write(source, A, B, C)
    f.poll()
    assert f.output.texts() == [A, B, C]
    assert not any(line.removed_from_input for line in f.output.lines)
    write(source, B, A, C)
    f.poll()
    assert f.output.texts() == [A, B, C]


def test_a_removed_output_line_is_not_brought_back(files: tuple[Path, Path]) -> None:
    source, _ = files
    write(source, A, B)
    f = follow(files)
    f.poll()
    f.output.remove(1)
    write(source, A, B, C)
    f.poll()
    assert f.output.texts() == [A, C]


def test_a_restart_knows_what_it_took(files: tuple[Path, Path]) -> None:
    source, _ = files
    write(source, A, B)
    follow(files).poll()
    edited = "2#20389 11:35:21.500#nextLap#"
    write(source, A, edited, C)
    again = follow(files)
    again.poll()
    assert again.output.texts() == [A, B, C]
    assert again.lines[1] == InputLine(edited, B)


def test_lines_already_in_a_chosen_output_are_not_taken_twice(
    files: tuple[Path, Path],
) -> None:
    source, out = files
    write(out, B, A)
    write(source, A, B, C)
    f = follow(files)
    f.poll()
    assert f.output.texts() == [A, B, C]
    assert [line.origin for line in f.output.lines] == [
        {"input": A},
        {"input": B},
        {"input": C},
    ]


def test_an_emptied_input_marks_its_lines_and_new_ones_arrive(
    files: tuple[Path, Path],
) -> None:
    source, _ = files
    write(source, A, B)
    f = follow(files)
    f.poll()
    write(source)
    f.poll()
    assert all(line.removed_from_input for line in f.output.lines)
    write(source, C)
    f.poll()
    assert f.output.texts() == [A, B, C]
    assert not f.output.lines[2].removed_from_input


def test_lines_not_written_are_read_again_at_the_next_poll(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _ = files
    f = follow(files)
    write(source, A)
    real = output_list._write_in_one_step

    def full(_path: Path, _data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(output_list, "_write_in_one_step", full)
    with pytest.raises(OSError, match="disk full"):
        f.poll()
    assert f.output.texts() == []
    monkeypatch.setattr(output_list, "_write_in_one_step", real)
    assert f.poll()
    assert f.output.texts() == [A]


def test_a_last_line_left_without_its_line_break_is_taken_once_at_rest(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _ = files
    write(source, A, tail=B)  # B without its line break, the file just written
    now = source.stat().st_mtime_ns
    clock = {"ns": now + 100_000_000}
    monkeypatch.setattr(input_follow.time, "time_ns", lambda: clock["ns"])
    f = follow(files)
    assert f.poll()
    assert f.output.texts() == [A]  # it may still be being written
    assert not f.poll()
    clock["ns"] = now + 3_000_000_000  # left so: the tool is done with it
    assert f.poll()
    assert f.output.texts() == [A, B]
    assert not f.poll()
    write(source, A, tail=" \n")
    f.poll()
    assert not f._cut  # blanks after the last line break are no line


def test_the_only_line_taken_edited_is_a_change_not_a_new_file() -> None:
    taken = ["5#0 10:0:0.000#finish#"]
    edited = ["5#0 10:0:1.000#finish#"]
    result = align(taken, edited)
    assert (result.new, result.gone) == ([], [])
    assert result.shown == [InputLine(edited[0], taken[0])]
    later = align(taken, ["5#0 11:0:0.000#finish#", "8##"])  # an hour on: a new race
    assert (later.new, later.gone) == (["5#0 11:0:0.000#finish#", "8##"], taken)
    timeless = align(["7##"], ["8##"])  # nothing to tell by: a new file
    assert timeless.new == ["8##"]
