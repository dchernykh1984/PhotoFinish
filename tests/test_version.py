"""The program's version, read as a window and its recorders read it."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from app import version as version_module


def test_the_version_is_the_one_pyproject_gives() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as f:
        expected = tomllib.load(f)["project"]["version"]
    version_module.version.cache_clear()
    assert version_module.version() == expected


def test_a_frozen_build_reads_the_copy_it_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.8.7"\n')
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    version_module.version.cache_clear()
    try:
        assert version_module.version() == "9.8.7"
    finally:
        version_module.version.cache_clear()


@pytest.mark.parametrize("text", [None, "not toml [", "[tool]\nx = 1\n"])
def test_a_build_without_a_readable_version_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str | None
) -> None:
    if text is not None:
        (tmp_path / "pyproject.toml").write_text(text)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    version_module.version.cache_clear()
    try:
        assert version_module.version() == ""
    finally:
        version_module.version.cache_clear()
