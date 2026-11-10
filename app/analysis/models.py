"""The detection models PhotoFinish offers, fetched once and checked (002, FR-003).

Each is a YOLOX COCO detector from the YOLOX releases (Apache-2.0), pinned by size
and SHA-256. The first time the referee chooses one it is downloaded next to the
program and kept, so the race itself needs no internet; a download cut short or
not the one pinned is never kept under the model's name.
"""

from __future__ import annotations

import hashlib
import http.client
import math
import ssl
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import certifi

from app.paths import app_path

FOLDER = "models"  # next to the program, beside data/ and video/
_RELEASE = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/"
_CHUNK = 1 << 16
TIMEOUT_S = 30


@dataclass(frozen=True)
class Model:
    key: str
    title: str
    size: int  # bytes
    sha256: str

    @property
    def file(self) -> str:
        """Where the session keeps it: relative, so a copied event folder keeps it."""
        return f"{FOLDER}/{self.key}.onnx"

    @property
    def url(self) -> str:
        return f"{_RELEASE}{self.key}.onnx"

    @property
    def megabytes(self) -> int:
        return math.ceil(self.size / 1_000_000)

    @property
    def label(self) -> str:
        return f"{self.title} ({self.megabytes} MB)"


MODELS = (
    Model(
        "yolox_nano",
        "YOLOX-Nano, the fastest",
        3_659_407,
        "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d",
    ),
    Model(
        "yolox_tiny",
        "YOLOX-Tiny",
        20_219_662,
        "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7",
    ),
    Model(
        "yolox_s",
        "YOLOX-S, finds the most",
        35_858_002,
        "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
    ),
)

type Opener = Callable[[str], BinaryIO]


class FetchError(Exception):
    """The model was not fetched: what the referee is told."""


def preset(chosen: str) -> Model | None:
    """The preset the session's model file is, if it is one."""
    return next((m for m in MODELS if m.file == chosen), None)


def ready(model: Model) -> bool:
    """The model is next to the program, whole. Its checksum was checked when it
    was downloaded, the only way a file gets its name: checked again here, it
    would hold the window up hashing tens of megabytes."""
    path = app_path(model.file)
    return path.is_file() and path.stat().st_size == model.size


def fetch(
    model: Model,
    progress: Callable[[int], None] = lambda done: None,
    opener: Opener | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Path:
    """The model downloaded next to the program and checked; ``progress`` hears the
    bytes so far at each whole megabyte and at the end, not at every chunk; once
    ``cancelled`` says so the download stops. Raises FetchError, leaving nothing
    under the model's name."""
    path = app_path(model.file)
    part = path.with_name(path.name + ".part")
    digest, done, told = hashlib.sha256(), 0, -1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with (opener or _open)(model.url) as reply, part.open("wb") as out:
            while chunk := reply.read(_CHUNK):
                if cancelled():
                    raise FetchError(f"{model.title}: download stopped")
                done += len(chunk)
                if done > model.size:
                    raise FetchError(f"{model.title}: more than the model pinned")
                digest.update(chunk)
                out.write(chunk)
                if done // 1_000_000 > told or done == model.size:
                    told = done // 1_000_000
                    progress(done)
        if done != model.size or digest.hexdigest() != model.sha256:
            raise FetchError(f"{model.title}: the download is not the model pinned")
        part.replace(path)
    except (OSError, http.client.HTTPException) as error:  # network, disk, a reply cut
        part.unlink(missing_ok=True)
        raise FetchError(f"{model.title} cannot be downloaded: {error}") from error
    except FetchError:
        part.unlink(missing_ok=True)
        raise
    return path


def _open(url: str) -> Any:
    # certifi's roots: a frozen build may not find the system's
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(url, timeout=TIMEOUT_S, context=context)  # noqa: S310 - a pinned https URL
