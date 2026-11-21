"""The numbers of a start protocol (specs/014-start-protocol)."""

from __future__ import annotations

import os
from pathlib import Path

from app.start_protocol import StartNumbers, loose, read_numbers

LINES = [  # StartProtocolMaker's start.txt: number, name, group, laps, stages, ...
    "12#Ivanov Ivan#M40##1#1980#Team#City##0 00:00:00.000###",
    "007#Petrov Petr#M40##1#1981#####",
    "101#Relay A / Relay B#Relay#3#2#####",
    "NOT_PAID#Unpaid Rider#M40##1#####",
    "A12#Lettered#Open##1#####",
    "",
]


def protocol(tmp_path: Path, lines: list[str], encoding: str = "utf-8") -> Path:
    path = tmp_path / "start.txt"
    path.write_text("\n".join(lines), encoding=encoding)
    return path


def test_a_start_protocol_gives_its_numbers_and_a_relays_stages(tmp_path: Path) -> None:
    numbers = read_numbers(protocol(tmp_path, LINES))
    assert numbers == {
        "12": "12",
        "7": "007",  # compared without its zeros, spelled as the protocol spells it
        "101": "101",
        "102": "102",  # the relay's second stage
        "A12": "A12",
    }


def test_a_table_with_the_number_first_is_read_too(tmp_path: Path) -> None:
    lines = ["Number;Name", "5;Sidorov", "6,Smirnov", '"8"\tKuznetsov']
    assert read_numbers(protocol(tmp_path, lines)) == {"5": "5", "6": "6", "8": "8"}


def test_cp1251_is_read_as_the_older_tools_wrote_it(tmp_path: Path) -> None:
    path = protocol(tmp_path, ["3#\u0418\u0432\u0430\u043d\u043e\u0432#M##1"], "cp1251")
    assert read_numbers(path) == {"3": "3"}


def test_numbers_are_compared_upper_case_without_leading_zeros() -> None:
    assert loose("007") == "7"
    assert loose("a012") == "A12"
    assert loose("0") == "0"
    assert loose("100") == "100"


def test_the_numbers_are_read_again_when_the_path_or_the_file_changes(
    tmp_path: Path,
) -> None:
    path = protocol(tmp_path, ["1#A"])
    chosen = [str(path)]
    numbers = StartNumbers(lambda: chosen[0])
    assert numbers() == {"1": "1"}
    path.write_text("1#A\n2#B\n", encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert numbers() == {"1": "1", "2": "2"}
    chosen[0] = ""
    assert numbers() == {}
    chosen[0] = str(tmp_path / "gone.txt")
    assert numbers() == {}  # a file that cannot be read: read as without one
    assert numbers.problem.startswith("the start protocol cannot be read")
