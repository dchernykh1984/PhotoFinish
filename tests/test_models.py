"""The detection models offered: fetched once, checked, never kept half-way."""

from __future__ import annotations

import hashlib
import http.client
import io
import os
import ssl
import urllib.error
from pathlib import Path
from typing import Any

import certifi
import pytest

from app.analysis import models
from app.analysis.models import FetchError, Model
from app.paths import app_path

CONTENT = bytes(range(256)) * 600  # several chunks
MODEL = Model(
    "yolox_test", "YOLOX-Test", len(CONTENT), hashlib.sha256(CONTENT).hexdigest()
)


def serving(content: bytes) -> Any:
    return lambda url: io.BytesIO(content)


def test_the_presets_are_pinned_yolox_detectors_from_the_yolox_releases() -> None:
    assert [m.key for m in models.MODELS] == ["yolox_nano", "yolox_tiny", "yolox_s"]
    for model in models.MODELS:
        assert model.url.startswith("https://github.com/Megvii-BaseDetection/YOLOX/")
        assert model.url.endswith(f"/{model.key}.onnx")
        assert model.file == f"models/{model.key}.onnx"
        assert len(model.sha256) == 64
    assert models.MODELS[2].label == "YOLOX-S, finds the most (36 MB)"
    assert models.preset("models/yolox_s.onnx") is models.MODELS[2]
    assert models.preset("/elsewhere/yolox_s.onnx") is None
    assert models.preset("") is None


def test_a_model_fetched_is_kept_next_to_the_program_and_ready(base: Path) -> None:
    assert not models.ready(MODEL)
    heard: list[int] = []
    path = models.fetch(MODEL, heard.append, serving(CONTENT))
    assert path == base / "models" / "yolox_test.onnx"
    assert path.read_bytes() == CONTENT
    assert heard == sorted(heard)
    assert heard[-1] == len(CONTENT)
    assert models.ready(MODEL)
    assert list(path.parent.iterdir()) == [path]  # no part left beside it


def test_progress_is_told_at_each_megabyte_not_at_each_chunk(base: Path) -> None:
    content = bytes(2_500_000)
    model = Model("yolox_big", "Big", len(content), hashlib.sha256(content).hexdigest())
    heard: list[int] = []
    models.fetch(model, heard.append, serving(content))
    assert [done // 1_000_000 for done in heard] == [0, 1, 2, 2]
    assert heard[-1] == len(content)
    assert model.megabytes == 3


@pytest.mark.parametrize(
    ("served", "said"),
    [
        (CONTENT[:-1] + b"x", "not the model pinned"),
        (CONTENT[:-10], "not the model pinned"),
        (CONTENT + b"x", "more than the model pinned"),
    ],
)
def test_a_download_that_is_not_the_model_pinned_is_not_kept(
    base: Path, served: bytes, said: str
) -> None:
    with pytest.raises(FetchError, match=said):
        models.fetch(MODEL, opener=serving(served))
    assert list((base / "models").iterdir()) == []
    assert not models.ready(MODEL)


def test_a_network_that_fails_is_said_and_leaves_nothing(base: Path) -> None:
    def offline(url: str) -> Any:
        raise urllib.error.URLError("no route to host")

    with pytest.raises(FetchError, match="YOLOX-Test cannot be downloaded"):
        models.fetch(MODEL, opener=offline)
    assert list((base / "models").iterdir()) == []


def test_a_download_stopped_leaves_nothing(base: Path) -> None:
    with pytest.raises(FetchError, match="YOLOX-Test: download stopped"):
        models.fetch(MODEL, opener=serving(CONTENT), cancelled=lambda: True)
    assert list((base / "models").iterdir()) == []


def test_a_reply_cut_short_is_said_and_leaves_nothing(base: Path) -> None:
    class Cut(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            raise http.client.IncompleteRead(b"partial")

    with pytest.raises(FetchError, match="YOLOX-Test cannot be downloaded"):
        models.fetch(MODEL, opener=lambda url: Cut())
    assert list((base / "models").iterdir()) == []


def test_a_model_is_on_the_disk_before_it_takes_its_name_and_waits_for_a_scanner(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synced before the rename, so a power cut cannot leave a model of the right
    size full of nothing; renamed again while Windows' virus scanner holds it."""
    synced: list[int] = []
    real_fsync, real_replace = os.fsync, Path.replace
    held = [2]  # the scanner lets go after two tries

    def fsync(fd: int) -> None:
        synced.append(fd)
        real_fsync(fd)

    def replace(self: Path, target: Path) -> Path:
        if held[0]:
            held[0] -= 1
            raise PermissionError("held by another process")
        assert synced  # synced first
        return real_replace(self, target)

    monkeypatch.setattr(models.os, "fsync", fsync)
    monkeypatch.setattr(Path, "replace", replace)
    path = models.fetch(MODEL, opener=serving(CONTENT))
    assert path.read_bytes() == CONTENT
    assert held == [0]


def test_a_model_cut_short_on_disk_is_not_ready(base: Path) -> None:
    path = models.fetch(MODEL, opener=serving(CONTENT))
    path.write_bytes(CONTENT[:-1])
    assert not models.ready(MODEL)


def test_the_download_trusts_certifis_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: dict[str, Any] = {}

    def urlopen(url: str, timeout: float, context: ssl.SSLContext) -> io.BytesIO:
        asked.update(url=url, timeout=timeout, context=context)
        return io.BytesIO(b"")

    loaded: list[str] = []
    real = ssl.create_default_context

    def context(cafile: str) -> ssl.SSLContext:
        loaded.append(cafile)
        return real(cafile=cafile)

    monkeypatch.setattr(models.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(models.ssl, "create_default_context", context)
    models._open(MODEL.url)
    assert asked["url"] == MODEL.url
    assert asked["timeout"] == models.TIMEOUT_S
    assert loaded == [certifi.where()]
    assert app_path(MODEL.file).name == "yolox_test.onnx"


def test_a_download_tells_its_answers_with_itself(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    heard: list[tuple[models.Download, object]] = []

    def say(job: models.Download, what: object) -> None:
        heard.append((job, what))

    monkeypatch.setattr(models, "_open", serving(CONTENT))
    job = models.Download(MODEL, say, say)
    job.run()
    assert heard[-1] == (job, "")
    assert all(told is job for told, _ in heard)
    assert models.ready(MODEL)


@pytest.mark.parametrize(
    ("failure", "said"),
    [
        (FetchError("YOLOX-Test: download stopped"), "YOLOX-Test: download stopped"),
        (ValueError("odd"), "YOLOX-Test cannot be downloaded: odd"),
    ],
)
def test_a_download_that_fails_tells_why(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, said: str
) -> None:
    def fetch(*args: object, **kwargs: object) -> Path:
        raise failure

    monkeypatch.setattr(models, "fetch", fetch)
    heard: list[str] = []
    models.Download(MODEL, lambda job, done: None, lambda job, e: heard.append(e)).run()
    assert heard == [said]


def test_a_download_cancelled_stops_at_its_next_read(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "_open", serving(CONTENT))
    heard: list[str] = []
    job = models.Download(MODEL, lambda job, done: None, lambda job, e: heard.append(e))
    job.cancel()
    job.run()
    assert heard == ["YOLOX-Test: download stopped"]
    assert not models.ready(MODEL)


def test_each_download_has_a_part_of_its_own_and_crashed_parts_go(base: Path) -> None:
    parts: list[set[str]] = []

    class Reply(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if self.tell() == 0:  # the part is open by the first read
                parts.append({p.name for p in (base / "models").glob("*.part")})
            return super().read(size)

    models.fetch(MODEL, opener=lambda url: Reply(CONTENT))
    models.fetch(MODEL, opener=lambda url: Reply(CONTENT))
    (first,), (second,) = parts
    assert first != second
    assert first.startswith("yolox_test.onnx.")
    crashed = base / "models" / "yolox_test.onnx.dead.part"
    crashed.write_bytes(b"x")
    models.clear_parts()
    assert not crashed.exists()
    assert (base / "models" / "yolox_test.onnx").exists()
