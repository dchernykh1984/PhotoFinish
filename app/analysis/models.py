"""The detection models PhotoFinish offers, fetched once and checked (002, FR-003).

Each is a YOLOX COCO detector from the YOLOX releases (Apache-2.0), pinned by size
and SHA-256. The first time the referee chooses one it is downloaded next to the
program and kept, so the race itself needs no internet; a download cut short or
not the one pinned is never kept under the model's name.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import math
import os
import secrets
import ssl
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import certifi

from app import files
from app.paths import app_path

FOLDER = "models"  # next to the program, beside data/ and video/
_RELEASE = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/"
_CHUNK = 1 << 16
TIMEOUT_S = 30
STALE_S = 600  # a part not written to for this long belongs to no download


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
    # A part of its own: a download stopped and still ending never touches the
    # next one's.
    part = path.with_name(f"{path.name}.{secrets.token_hex(4)}.part")
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
            out.flush()
            os.fsync(out.fileno())  # on the disk before it takes the model's name
        if done != model.size or digest.hexdigest() != model.sha256:
            raise FetchError(f"{model.title}: the download is not the model pinned")
        files.replace(part, path)  # a virus scanner holding it a moment: again
    except (OSError, http.client.HTTPException) as error:  # network, disk, a reply cut
        _drop(part)
        raise FetchError(f"{model.title} cannot be downloaded: {error}") from error
    except BaseException:  # whatever else stopped it: nothing half-way is kept
        _drop(part)
        raise
    return path


def _drop(part: Path) -> None:
    with contextlib.suppress(OSError):  # one a scanner holds: for clear_parts
        part.unlink(missing_ok=True)


def clear_parts() -> None:
    """The parts downloads cut short by a crash left behind: those not written to
    for STALE_S, since a newer one may be another window's download still going.
    One that cannot go -- a scanner holds it on Windows -- waits for the next start.
    """
    for part in app_path(FOLDER).glob("*.part"):
        with contextlib.suppress(OSError):
            if time.time() - part.stat().st_mtime > STALE_S:
                part.unlink()


class Download:
    """One download of a model, on a thread of its own. ``cancel()`` stops it. Its
    progress and its end are told with the download itself, so whoever started
    it tells its answers from those of one since stopped, even of the same model.
    """

    def __init__(
        self,
        model: Model,
        progress: Callable[[Download, int], None],
        done: Callable[[Download, str], None],
    ) -> None:
        self.model = model
        self._progress, self._done = progress, done
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True).start()

    def cancel(self) -> None:
        self._stop.set()

    def run(self) -> None:
        """The download, its end told: what went wrong, or nothing once it is there."""
        try:
            fetch(
                self.model,
                lambda done: self._progress(self, done),
                cancelled=self._stop.is_set,
            )
        except FetchError as error:
            self._done(self, str(error))
        except Exception as error:  # whatever else: told, never left waiting
            self._done(self, f"{self.model.title} cannot be downloaded: {error}")
        else:
            self._done(self, "")


def _open(url: str) -> Any:
    # certifi's roots: a frozen build may not find the system's
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(url, timeout=TIMEOUT_S, context=context)  # noqa: S310 - a pinned https URL
