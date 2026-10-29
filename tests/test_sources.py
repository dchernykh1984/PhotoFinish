"""Camera connections opened as sources of frames or packets."""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import numpy as np
import pytest

from app import cameras
from app.recorder import sources
from app.recorder.segments import SegmentWriter
from app.recorder.sources import (
    Anchor,
    CameraSettingsError,
    LiveFile,
    UsbCamera,
    open_source,
    usb_input,
)
from app.recorder.testcam import render

START = 1_761_716_129_587


def test_a_test_camera_opens_with_its_settings() -> None:
    camera = {"connection": "test", "settings": {"fps": 60, "scene": "bar"}}
    source = open_source(camera, clock=lambda: START)
    assert (source.fps, source.waiting) == (60, "")
    item = next(source.frames())
    assert item is not None
    image, ms = item
    assert isinstance(image, np.ndarray)
    assert (image.shape, ms) == ((360, 640, 3), START)


def test_a_camera_that_cannot_record_is_refused_with_the_reason() -> None:
    with pytest.raises(CameraSettingsError, match="scene"):
        open_source({"connection": "test", "settings": {"scene": "rain"}}, lambda: 0)


def test_what_only_the_window_uses_never_stops_a_recording() -> None:
    camera = {
        "connection": "test",
        "settings": {"fps": 10},
        "finish_line": [[0.5, 0.5], [0.5, 0.5]],
        "zone": [[0.3, 0.2], [0.3, 0.8]],
        "offset_ms": "soon",
    }
    assert next(open_source(camera, lambda: START).frames()) is not None


def test_moments_follow_the_camera_timestamps_from_the_first() -> None:
    now = {"ms": START}
    anchor = Anchor(lambda: now["ms"])
    assert anchor(5000.0) == START
    now["ms"] += 100  # arrival jitter does not move frames
    assert anchor(5033.4) == START + 33
    assert anchor(5010.0) == START + 10  # a frame shown before the last
    assert anchor(None) == START + 100
    assert anchor(3000.0) == START + 100  # back by more than a second
    now["ms"] += 7000
    assert anchor(9000.0) == START + 7100  # forward by more than five


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", ("PC Camera:none", "avfoundation")),
        ("win32", ("video=PC Camera", "dshow")),
        ("linux", ("PC Camera", "video4linux2")),
    ],
)
def test_a_usb_camera_is_named_as_its_platform_names_it(
    monkeypatch: pytest.MonkeyPatch, platform: str, expected: tuple[str, str]
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    assert usb_input("PC Camera") == expected


class Container:
    """Stands for what av.open gives: frames, or packets, and a context."""

    def __init__(self, frames: list[Any]) -> None:
        self._frames = frames

    def __enter__(self) -> Container:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def decode(self, video: int) -> Iterator[Any]:
        return iter(self._frames)


def test_a_usb_camera_gives_frames_at_its_own_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: dict[str, Any] = {}
    frames = [av.VideoFrame(64, 64, "rgb24") for _ in range(3)]
    for k, frame in enumerate(frames):
        frame.pts, frame.time_base = 1000 + k * 40, Fraction(1, 1000)

    def fake_open(device: str, **options: Any) -> Container:
        opened.update(options, device=device)
        return Container(frames)

    monkeypatch.setattr(av, "open", fake_open)
    monkeypatch.setattr(cameras, "usb_capture", lambda: "avfoundation")
    settings = {"device": "PC Camera", "width": 1280, "height": 720, "fps": 25}
    camera = open_source({"connection": "usb", "settings": settings}, lambda: START)
    assert isinstance(camera, UsbCamera)
    moments = [item[1] for item in camera.frames() if item is not None]
    assert moments == [START, START + 40, START + 80]
    assert opened["options"] == {"framerate": "25", "video_size": "1280x720"}
    assert opened["timeout"] == (sources.OPEN_TIMEOUT_S, sources.READ_TIMEOUT_S)


def make_video(path: Path, frames: int, fps: int = 25) -> None:
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
        for k in range(frames):
            frame = av.VideoFrame.from_ndarray(render(START + k * 40, 640, 360))
            frame.pts = k
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def test_a_file_plays_as_if_filmed_now(tmp_path: Path) -> None:
    make_video(tmp_path / "race.mkv", 10)
    now = {"ms": START}

    def sleep(seconds: float) -> None:
        now["ms"] += round(seconds * 1000)

    camera = {"connection": "file", "settings": {"path": str(tmp_path / "race.mkv")}}
    source = open_source(camera, lambda: now["ms"], sleep)
    assert isinstance(source, LiveFile)
    moments = [item[1] for item in source.frames() if item is not None]
    assert moments == [START + k * 40 for k in range(10)]
    assert source.fps == 25
    assert now["ms"] == START + 360


def test_a_stream_that_does_not_answer_fails_to_be_opened_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def silent(url: str, **options: Any) -> None:
        raise TimeoutError("no answer")

    monkeypatch.setattr(av, "open", silent)
    camera = {"connection": "rtsp", "settings": {"url": "rtsp://192.168.1.254/x"}}
    with pytest.raises(TimeoutError):
        next(open_source(camera, lambda: START).frames())


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def push(port: int, frames: int) -> None:
    """What a camera app does: H.264 over RTMP to this computer, a keyframe a second."""
    url = f"rtmp://127.0.0.1:{port}/live/test"
    with av.open(url, "w", format="flv") as container:
        options = {"g": "30", "tune": "zerolatency", "preset": "ultrafast"}
        stream = container.add_stream("libx264", rate=30, options=options)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
        for k in range(frames):
            frame = av.VideoFrame.from_ndarray(render(START + k * 33, 640, 360))
            frame.pts = k
            for packet in stream.encode(frame):
                container.mux(packet)
            time.sleep(1 / 30)
        for packet in stream.encode(None):
            container.mux(packet)


def test_an_rtmp_push_is_received_and_kept_as_it_came(tmp_path: Path) -> None:
    port = free_port()
    camera = {"connection": "rtmp", "settings": {"port": port, "path": "live/test"}}
    source = open_source(camera, lambda: time.time_ns() // 1_000_000)
    assert source.waiting.startswith("waiting for rtmp://")
    assert source.waiting.endswith(f":{port}/live/test")
    writer = SegmentWriter(tmp_path, fps=30)
    got = {"waits": 0, "packets": 0}

    def receive() -> None:
        try:
            for item in source.frames():
                if item is None:
                    got["waits"] += 1
                    continue
                packet, ms = item
                assert isinstance(packet, av.Packet)
                writer.write_packet(packet, ms)
                got["packets"] += 1
        except OSError:
            pass  # the camera app hung up
        writer.close()

    thread = threading.Thread(target=receive)
    thread.start()
    time.sleep(1.5)
    push(port, 90)
    thread.join(timeout=30)
    assert got["waits"] >= 1
    assert got["packets"] == 90
    assert source.fps == 30
    closed = sorted(tmp_path.glob("*-*-*.mkv"))
    assert len(closed) == 3
    for path in closed:
        lines = path.with_suffix(".times").read_text().split("\n")[:-1]
        pts = [int(line.split()[0]) for line in lines]
        with av.open(str(path)) as container:
            assert [f.pts for f in container.decode(video=0)] == sorted(pts)


def test_moments_follow_a_camera_whose_clock_drifts_from_the_computers() -> None:
    for drift in (1.0001, 0.9999):  # 100 ppm either way, four hours
        now = {"ms": float(START)}

        def clock(now: dict[str, float] = now) -> int:
            return round(now["ms"])

        anchor = Anchor(clock)
        last = 0
        for second in range(4 * 3600):
            now["ms"] += 1000 * drift + (37 if second % 7 == 0 else 0) - 37 / 7
            moment = anchor(float(second * 1000))
            assert moment >= last
            last = moment
        assert abs(last - now["ms"]) < 60  # within the jitter, not 1.4 s off
