"""Camera connections opened as sources of frames or packets."""

from __future__ import annotations

import io
import itertools
import socket
import struct
import sys
import threading
import time
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import av
import numpy as np
import pytest

from app import cameras
from app.recorder import frame_time, sources
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
from tests.test_frame_time import avcc, sei, status_sei

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


def test_a_file_camera_s_path_is_found_in_the_event_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import paths

    make_video(tmp_path / "race.mkv", 3)
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)  # not the working dir
    camera = {"connection": "file", "settings": {"path": "race.mkv"}}
    source = open_source(camera, lambda: START, lambda seconds: None)
    assert len([item for item in source.frames() if item is not None]) == 3


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


def push(port: int, frames: int, moment_us: Any = None) -> None:
    """What a camera app does: H.264 over RTMP to this computer, a keyframe a second;
    each frame after the SEI of ``moment_us(frame)``, as PhotoFinish Camera does."""
    url = f"rtmp://127.0.0.1:{port}/live/test"
    with av.open(url, "w", format="flv") as container:
        options = {"g": "30", "tune": "zerolatency", "preset": "ultrafast"}
        stream = container.add_stream("libx264", rate=30, options=options)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"

        def send(packets: list[av.Packet]) -> None:
            for packet in packets:
                moment = None if moment_us is None else moment_us(packet.pts)
                if moment is not None:
                    stamped = av.Packet(
                        b"\x00\x00\x00\x01" + sei(moment) + bytes(packet)
                    )
                    stamped.pts, stamped.dts = packet.pts, packet.dts
                    stamped.time_base, stamped.stream = packet.time_base, stream
                    stamped.is_keyframe = packet.is_keyframe
                    packet = stamped
                container.mux(packet)

        for k in range(frames):
            frame = av.VideoFrame.from_ndarray(render(START + k * 33, 640, 360))
            frame.pts = k
            send(stream.encode(frame))
            time.sleep(1 / 30)
        send(stream.encode(None))


def test_the_address_waited_on_is_this_computer_s_as_it_is_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    here = ["127.0.0.1"]  # started before the computer joined the race Wi-Fi
    looked_on: list[threading.Thread] = []

    def this_computer() -> str:
        looked_on.append(threading.current_thread())
        return here[0]

    now = {"s": 100.0}
    monkeypatch.setattr(cameras, "this_computer", this_computer)
    monkeypatch.setattr(time, "monotonic", lambda: now["s"])
    camera = {"connection": "rtmp", "settings": {"port": 1936, "path": "live/x"}}
    source = open_source(camera, lambda: START)
    assert source.waiting == "waiting for rtmp://127.0.0.1:1936/live/x"
    here[0] = "192.168.1.20"
    now["s"] += 1  # said every second while it waits
    assert source.waiting == "waiting for rtmp://127.0.0.1:1936/live/x"
    assert len(looked_on) == 1  # not looked up each time: with no network it may wait
    now["s"] += 10
    source.waiting  # noqa: B018 -- the look-up begins, off the recorder's loop
    for _ in range(500):
        if source.waiting.endswith("192.168.1.20:1936/live/x"):
            break
        threading.Event().wait(0.01)
    assert source.waiting == "waiting for rtmp://192.168.1.20:1936/live/x"
    assert looked_on[-1] is not threading.current_thread()


def test_a_slow_address_lookup_is_not_begun_again_until_it_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    slow = threading.Event()

    def this_computer() -> str:
        calls.append(1)
        if len(calls) > 1:
            slow.wait(5)  # no network: the name lookup hangs
        return "10.0.0.5"

    now = {"s": 100.0}
    monkeypatch.setattr(cameras, "this_computer", this_computer)
    monkeypatch.setattr(time, "monotonic", lambda: now["s"])
    camera = {"connection": "rtmp", "settings": {"port": 1937, "path": "live/x"}}
    source = open_source(camera, lambda: START)
    for _ in range(3):  # half a minute of waiting, the lookup still under way
        now["s"] += 11
        source.waiting  # noqa: B018
    slow.set()
    assert len(calls) == 2  # the one at the open, and one more: not one a time


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


def receive_phone(moment_us: Any) -> list[int]:
    """The moments the frames of a phone stamping ``moment_us(frame)`` get."""
    port = free_port()
    camera = {"connection": "rtmp", "settings": {"port": port, "path": "live/test"}}
    source = open_source(camera, lambda: time.time_ns() // 1_000_000)
    got: list[int] = []

    def receive() -> None:
        try:
            for item in source.frames():
                if item is not None:
                    got.append(item[1])
        except OSError:
            pass  # the camera app hung up

    thread = threading.Thread(target=receive)
    thread.start()
    time.sleep(1.5)
    push(port, 20, moment_us)
    thread.join(timeout=30)
    assert len(got) == 20
    return got


def test_a_phone_camera_s_frames_keep_the_moments_it_wrote_in_them() -> None:
    # 40 ms apart while they are sent 33 ms apart: placed by their moments.
    first: list[int] = []

    def moment_us(k: int) -> int:
        first[:] = first or [time.time_ns() // 1000]  # the first frame's, as sent
        return first[0] + k * 40_000

    got = receive_phone(moment_us)
    assert got == [(first[0] + 500) // 1000 + k * 40 for k in range(20)]


def test_a_phone_s_moments_hold_though_ffmpeg_reads_its_first_seconds_late() -> None:
    # FFmpeg looks a stream over before it gives its first frames: these come seconds
    # after they were taken, and an anchor on their arrival is that far off.
    first: list[int] = []

    def moment_us(k: int) -> int:
        first[:] = first or [time.time_ns() // 1000 - 4_000_000]
        return first[0] + k * 33_333

    got = receive_phone(moment_us)
    assert got == [(first[0] + k * 33_333 + 500) // 1000 for k in range(20)]


def test_a_push_s_first_frames_are_given_soon_not_after_seconds_of_look_over() -> None:
    port = free_port()
    camera = {"connection": "rtmp", "settings": {"port": port, "path": "live/test"}}
    source = open_source(camera, lambda: time.time_ns() // 1_000_000)
    first: list[int] = []

    def moment_us(k: int) -> int:
        return time.time_ns() // 1000  # each frame's moment: as it is encoded

    def receive() -> None:
        try:
            for item in source.frames():
                if item is not None and not first:
                    first.append(time.time_ns() // 1_000_000 - item[1])
        except OSError:
            pass  # the camera app hung up

    thread = threading.Thread(target=receive)
    thread.start()
    time.sleep(1.5)
    push(port, 90, moment_us)  # three seconds: FFmpeg's look-over would wait them out
    thread.join(timeout=30)
    assert first and first[0] < 1500  # the first frame, read well within its seconds


def test_a_push_whose_sound_comes_first_is_still_recorded() -> None:
    # A streaming app may send a second of sound before its first picture: half a
    # second's look-over must still find the video.
    port = free_port()
    camera = {"connection": "rtmp", "settings": {"port": port, "path": "live/test"}}
    source = open_source(camera, lambda: time.time_ns() // 1_000_000)
    got: list[int] = []

    def receive() -> None:
        try:
            for item in source.frames():
                if item is not None:
                    got.append(item[1])
        except OSError:
            pass  # the app hung up

    thread = threading.Thread(target=receive)
    thread.start()
    time.sleep(1.5)
    url = f"rtmp://127.0.0.1:{port}/live/test"
    with av.open(url, "w", format="flv") as out:
        sound = out.add_stream("aac", rate=44100)
        sound.layout = "mono"
        options = {"g": "30", "tune": "zerolatency", "preset": "ultrafast"}
        video = out.add_stream("libx264", rate=30, options=options)
        video.width, video.height, video.pix_fmt = 640, 360, "yuv420p"
        for k in range(43):  # a second of silence
            frame = av.AudioFrame.from_ndarray(
                np.zeros((1, 1024), dtype=np.float32), format="fltp", layout="mono"
            )
            frame.sample_rate, frame.pts = 44100, k * 1024
            for packet in sound.encode(frame):
                out.mux(packet)
            time.sleep(1024 / 44100)
        for k in range(30):
            picture = av.VideoFrame.from_ndarray(render(START + k * 33, 640, 360))
            picture.pts = k
            for packet in video.encode(picture):
                out.mux(packet)
            time.sleep(1 / 30)
        for packet in video.encode(None):
            out.mux(packet)
    thread.join(timeout=30)
    assert len(got) == 30
    assert source.fps == 30


def test_a_phone_s_frames_keep_their_order_where_its_moments_begin() -> None:
    first: list[int] = []

    def moment_us(k: int) -> int | None:
        if k < 10:
            return None  # its clock not in step yet: placed by their arrival
        first[:] = first or [time.time_ns() // 1000 - 300_000]  # taken earlier
        return first[0] + (k - 10) * 33_333

    got = receive_phone(moment_us)
    assert all(b > a for a, b in itertools.pairwise(got))


def test_b_frames_keep_their_moments_among_frames_kept_in_order() -> None:
    source = sources.Stream("rtsp://10.0.0.2/live", {}, lambda: START)
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000),
        codec_context=SimpleNamespace(name="hevc", extradata=b""),
    )
    place = source._placing(stream)  # type: ignore[arg-type]
    decoded = [0, 99, 33, 66]  # I, P, then the B-frames between them
    assert [place(None, pts) for pts in decoded] == [START + pts for pts in decoded]  # type: ignore[arg-type]


def test_a_camera_this_computer_reads_is_not_looked_into_for_moments() -> None:
    # Only a phone pushing here writes them: an RTSP camera's frames are not copied.
    source = sources.Stream("rtsp://10.0.0.2/live", {}, lambda: START)
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000),
        codec_context=SimpleNamespace(name="h264", extradata=b"\x01\x64\x00\x28"),
    )
    place = source._placing(stream)  # type: ignore[arg-type]
    packet = avcc(sei((START - 500) * 1000), b"\x65\x88")
    assert place(packet, 0) == START  # type: ignore[arg-type]


def test_a_phone_s_moment_seconds_behind_the_recorder_is_not_believed() -> None:
    # The recorder's clock read again after a sleep, before the phone's next exchange.
    got = receive_phone(lambda k: time.time_ns() // 1000 - 8_000_000)  # 8 s behind
    now = time.time_ns() // 1_000_000
    assert all(now - 3_000 < ms <= now + 1_000 for ms in got)  # placed by arrival


def test_a_phone_s_stream_says_when_its_frames_come_without_moments() -> None:
    now = {"ms": START}
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: now["ms"], listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000),
        codec_context=SimpleNamespace(name="h264", extradata=b"\x01"),
    )
    place = source._placing(stream, phone=True)  # type: ignore[arg-type]
    place(avcc(b"\x65\x88"), 0)  # type: ignore[arg-type]
    assert sources.UNSTAMPED == source.clock_note
    place(avcc(sei(START * 1000), b"\x41\x9a"), 33)  # type: ignore[arg-type]
    assert sources.UNSTAMPED == source.clock_note  # begun without: by arrival
    stamped = source._placing(stream, phone=True)  # type: ignore[arg-type]
    stamped(avcc(sei(START * 1000), b"\x65\x88"), 0)  # type: ignore[arg-type]
    assert not source.clock_note  # the next connection, stamped from its start
    streaming_app = source._placing(stream, phone=False)  # type: ignore[arg-type]
    streaming_app(avcc(b"\x65\x88"), 66)  # type: ignore[arg-type]
    assert not source.clock_note  # Larix and the like never carry them


def test_a_phone_s_keyframes_tell_its_status_kept_through_a_new_connection() -> None:
    now = {"ms": START}
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: now["ms"], listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )
    place = source._placing(stream, phone=True)  # type: ignore[arg-type]
    assert source.phone == {}
    status = status_sei(b"battery=57;charging=1")
    place(avcc(sei(START * 1000), status, b"\x65\x88"), 0)  # type: ignore[arg-type]
    heard = source.phone.pop("heard_ms")
    assert abs(heard - time.time_ns() // 1_000_000) < 60_000  # this computer's clock
    assert source.phone == {"battery": "57", "charging": "1", "at_ms": START}
    now["ms"] = START + 5_000
    again = source._placing(stream, phone=True)  # type: ignore[arg-type]
    again(avcc(sei((START + 4_990) * 1000), b"\x41\x9a"), 33)  # type: ignore[arg-type]
    assert source.phone["at_ms"] == START  # the last status kept, with its time
    rtsp = sources.Stream("rtsp://10.0.0.2/live", {}, lambda: START)
    rtsp._placing(stream)(avcc(status, b"\x65\x88"), 0)  # type: ignore[arg-type]
    assert rtsp.phone == {}  # a camera this computer reads is not looked into


def test_a_phone_s_frame_held_up_on_the_way_keeps_its_own_moment() -> None:
    now = {"ms": START}
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: now["ms"], listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )
    place = source._placing(stream, phone=True)  # type: ignore[arg-type]
    assert place(avcc(sei((START - 300) * 1000), b"\x65\x88"), 0) == START - 300  # type: ignore[arg-type]
    now["ms"] = START + 7_000  # Wi-Fi held the next frame up for seconds
    late = place(avcc(sei((START - 267) * 1000), b"\x41\x9a"), 33)  # type: ignore[arg-type]
    assert late == START - 267  # its own moment still: the phone's clock is in step


def test_a_phone_s_moment_from_the_future_is_not_believed() -> None:
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: START, listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )
    place = source._placing(stream, phone=True)  # type: ignore[arg-type]
    # A frame is read after it was taken: 1.5 s ahead is a clock out of step.
    assert place(avcc(sei((START + 1_500) * 1000), b"\x65\x88"), 0) == START  # type: ignore[arg-type]
    assert sources.NOT_IN_STEP == source.clock_note  # stamped, but out of step


def test_a_phone_s_frame_it_kept_through_a_break_keeps_its_own_moment() -> None:
    # specs/007: a connection that begins with frames the phone kept during a break
    # says how long it held the first; their moments are believed that much older.
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: START, listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )
    kept = source._placing(stream, phone=True, held=60_000)  # type: ignore[arg-type]
    assert kept(avcc(sei((START - 61_000) * 1000), b"\x65\x88"), 0) == START - 61_000  # type: ignore[arg-type]
    assert not source.clock_note
    beyond = source._placing(stream, phone=True, held=60_000)  # type: ignore[arg-type]
    first = avcc(sei((START - 70_000) * 1000), b"\x65\x88")
    assert beyond(first, 0) == START - 60_000  # type: ignore[arg-type]
    assert sources.NOT_IN_STEP == source.clock_note  # older than it says: out of step
    # ... and placed by its arrival, less the time the phone says it held it
    fresh = sources.Stream("rtmp://0.0.0.0:1935/live/x", {}, lambda: START, listen=True)
    unsaid = fresh._placing(stream, phone=True)  # type: ignore[arg-type]
    assert unsaid(avcc(sei((START - 61_000) * 1000), b"\x65\x88"), 0) == START  # type: ignore[arg-type]


def test_a_phone_s_frames_placed_by_arrival_and_sent_again_stay_where_they_were() -> (
    None
):
    # A phone out of step is placed by its arrival; after a loss it sends its last
    # second again, with the moments it kept them with: placed once (specs/007).
    now = {"ms": START}
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: now["ms"], listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )

    def frame(k: int) -> bytes:  # its moment a minute off: not believed
        return avcc(sei((START - 60_000 + k * 33) * 1000), b"\x41\x9a")

    first = source._placing(stream, phone=True)  # type: ignore[arg-type]
    placed = []
    for k in range(60):
        now["ms"] = START + k * 33  # each as it was taken: live
        placed.append(first(frame(k), k * 33))  # type: ignore[arg-type]
    now["ms"] = START + 10_000  # ten seconds of a break later
    held = now["ms"] - (START + 30 * 33)
    # The next connection is another Stream; the recorder hands it what it placed.
    next_one = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: now["ms"], listen=True
    )
    next_one.placed = source.placed
    again = next_one._placing(stream, phone=True, held=held)  # type: ignore[arg-type]
    resent = [again(frame(k), (k - 30) * 33) for k in range(30, 90)]  # type: ignore[arg-type]
    assert resent[:30] == placed[30:]  # the frames sent again, where they were
    assert abs(resent[30] - (START + 60 * 33)) < 50  # the next, as it was taken


def test_a_phone_s_new_frames_after_frames_sent_again_come_after_them() -> None:
    # The next connection's anchor, from when the phone says it took its first, may
    # fall before where the frames it sends again were placed, a slower network
    # then: the new frames still come after them.
    now = {"ms": START}
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: now["ms"], listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )

    def frame(k: int) -> bytes:  # its moment a minute off: not believed
        return avcc(sei((START - 60_000 + k * 33) * 1000), b"\x41\x9a")

    first = source._placing(stream, phone=True)  # type: ignore[arg-type]
    for k in range(60):
        now["ms"] = START + k * 33 + 150  # 150 ms on the way
        first(frame(k), k * 33)  # type: ignore[arg-type]
    now["ms"] = START + 10_000
    held = now["ms"] - (START + 30 * 33)
    again = source._placing(stream, phone=True, held=held)  # type: ignore[arg-type]
    moments = [again(frame(k), (k - 30) * 33) for k in range(30, 90)]  # type: ignore[arg-type]
    assert all(b > a for a, b in itertools.pairwise(moments))


@pytest.mark.parametrize(
    ("said", "held"),
    [("8123", 8123), ("8123.6", 8124), ("-5", 0), ("x", 0), ("inf", 0), ("nan", 0)],
)
def test_how_long_a_phone_held_its_first_frame_is_read_from_its_metadata(
    said: str, held: int
) -> None:
    assert sources.held_ms({"held_ms": said}) == held


def test_a_phone_says_nothing_of_holding_its_frames_none_is_read() -> None:
    assert sources.held_ms({"encoder": sources.PHONE_APP}) == 0


def test_ffmpeg_gives_the_number_a_phone_s_metadata_holds() -> None:
    # The phone writes held_ms as an AMF number; FFmpeg's FLV reader, which the RTMP
    # listener feeds, keeps it among the stream's metadata as text.
    def text(value: str) -> bytes:
        data = value.encode()
        return len(data).to_bytes(2) + data

    def tag(kind: int, data: bytes) -> bytes:
        head = bytes([kind]) + len(data).to_bytes(3) + bytes(7)
        return head + data + (len(head) + len(data)).to_bytes(4)

    meta = {"encoder": sources.PHONE_APP, "held_ms": 8123.0}
    body = b"\x02" + text("onMetaData") + b"\x08" + len(meta).to_bytes(4)
    for key, value in meta.items():
        body += text(key)
        if isinstance(value, str):
            body += b"\x02" + text(value)
        else:
            body += b"\x00" + struct.pack(">d", value)
    body += b"\x00\x00\x09"
    sps, pps = b"\x67\x42\x00\x1e", b"\x68\xce\x3c\x80"
    record = b"\x01\x42\x00\x1e\xff\xe1\x00\x04" + sps + b"\x01\x00\x04" + pps
    flv = b"FLV\x01\x01" + (9).to_bytes(4) + bytes(4)
    flv += tag(18, body) + tag(9, b"\x17\x00\x00\x00\x00" + record)
    with av.open(io.BytesIO(flv), format="flv") as container:
        assert sources.held_ms(container.metadata) == 8123


def test_a_stream_placed_by_arrival_is_looked_into_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked: list[int] = []
    real = frame_time.moment_ms

    def counted(packet: Any) -> int | None:
        looked.append(1)
        return real(packet)

    monkeypatch.setattr(frame_time, "moment_ms", counted)
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: START, listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )
    place = source._placing(stream, phone=False)  # type: ignore[arg-type]
    for k in range(3):  # Larix, say: no moments, all race long
        place(avcc(b"\x41\x9a"), k * 33)  # type: ignore[arg-type]
    assert len(looked) == 1


def test_a_phone_s_offset_moved_back_keeps_its_frames_in_order() -> None:
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: START, listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )
    place = source._placing(stream, phone=True)  # type: ignore[arg-type]
    assert place(avcc(sei((START - 300) * 1000), b"\x65\x88"), 0) == START - 300  # type: ignore[arg-type]
    # A better first exchange moves the phone's offset back by more than a frame.
    after = place(avcc(sei((START - 310) * 1000), b"\x41\x9a"), 33)  # type: ignore[arg-type]
    assert after == START - 299


def test_a_trusted_phone_s_frame_without_its_moment_is_placed_by_its_timestamp() -> (
    None
):
    now = {"ms": START}
    source = sources.Stream(
        "rtmp://0.0.0.0:1935/live/x", {}, lambda: now["ms"], listen=True
    )
    stream = SimpleNamespace(
        time_base=Fraction(1, 1000), codec_context=SimpleNamespace(name="h264")
    )
    place = source._placing(stream, phone=True)  # type: ignore[arg-type]
    assert place(avcc(sei((START - 300) * 1000), b"\x65\x88"), 0) == START - 300  # type: ignore[arg-type]
    now["ms"] = START + 2_000  # its arrival would put it seconds after the next
    assert place(avcc(b"\x41\x9a"), 33) == START - 267  # type: ignore[arg-type]


def test_a_phone_whose_clock_went_wrong_is_placed_by_arrival() -> None:
    got = receive_phone(lambda k: START * 1000 + k * 40_000)  # a year off
    now = time.time_ns() // 1_000_000
    assert all(abs(ms - now) < 10_000 for ms in got)


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
