"""The session file: defaults, kept keys, one-step writes."""

from __future__ import annotations

import json

import pytest

from app import paths, session


@pytest.fixture(autouse=True)
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    return tmp_path


def test_without_a_file_the_defaults_are_used() -> None:
    loaded = session.load()
    assert loaded == session.DEFAULTS
    loaded["cameras"].append({"id": "cam1"})
    assert session.DEFAULTS["cameras"] == []  # a copy, not the defaults themselves


def test_a_saved_session_comes_back_with_keys_this_version_does_not_know(
    folder,
) -> None:
    saved = {**session.DEFAULTS, "input": "results.txt", "later": {"x": 1}}
    saved["cameras"] = [{"id": "cam1", "name": "Side", "connection": "test"}]
    session.save(saved)
    assert session.load() == saved
    assert session.camera(saved, "cam1") == saved["cameras"][0]
    assert session.camera(saved, "cam9") is None
    assert not (folder / "data" / "session.json.tmp").exists()


def test_an_older_file_gets_the_keys_it_lacks(folder) -> None:
    (folder / "data").mkdir()
    (folder / "data" / "session.json").write_text(
        '{"input": "a.txt"}', encoding="utf-8"
    )
    loaded = session.load()
    assert loaded["input"] == "a.txt"
    assert loaded["source_offset_ms"] == 0


@pytest.mark.parametrize("text", ["{not json", "[1, 2]"])
def test_a_file_that_is_no_session_is_moved_aside(folder, text) -> None:
    (folder / "data").mkdir()
    (folder / "data" / "session.json").write_text(text, encoding="utf-8")
    assert session.load() == session.DEFAULTS
    (kept,) = (folder / "data").glob("session.json.broken-*")
    assert kept.read_text(encoding="utf-8") == text
    session.save(session.load())
    assert json.loads((folder / "data" / "session.json").read_text())["version"] == 1


def test_a_session_being_replaced_is_read_again_not_moved_aside(
    folder, monkeypatch
) -> None:
    from pathlib import Path

    from app import files

    session.save({**session.DEFAULTS, "input": "results.txt"})
    real = Path.read_bytes
    refused: list[Path] = []

    def read_bytes(self):
        if not refused:
            refused.append(self)
            raise PermissionError("being replaced")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(files.time, "sleep", lambda seconds: None)
    assert session.load()["input"] == "results.txt"
    assert refused


def test_a_session_that_cannot_be_read_is_left_where_it_is(folder, monkeypatch) -> None:
    from pathlib import Path

    from app import files

    session.save(session.DEFAULTS)

    def refuse(self):
        raise PermissionError("held")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    monkeypatch.setattr(files.time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        session.load()
    assert session.session_path().exists()
    assert not list(folder.glob("data/session.json.broken-*"))
