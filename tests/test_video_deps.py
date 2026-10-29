"""The video libraries the live editor builds on, and what it needs from them."""

from __future__ import annotations

import sys

import av
import numpy as np

from app import cameras


def test_the_recorder_s_encoder_and_container_are_there() -> None:
    assert "mpeg4" in av.codecs_available
    assert "matroska" in av.formats_available


def test_the_network_cameras_inputs_are_there() -> None:
    # RTSP for the SJCAM HD1080P over Wi-Fi; FLV is RTMP's container (SJ10 Pro).
    assert {"rtsp", "flv"} <= av.formats_available


def test_usb_cameras_are_captured_or_said_not_to_be() -> None:
    # The macOS and Windows wheels capture cameras; the Linux ones have no v4l2.
    if sys.platform in ("darwin", "win32"):
        assert cameras.usb_capture() is not None
    if cameras.usb_capture() is None:
        found = cameras.problems({"connection": "usb", "settings": {"device": "0"}})
        assert found == [
            "this build cannot capture USB cameras on this computer: "
            "use the camera's stream or a file"
        ]


def test_a_frame_goes_to_numpy_and_back() -> None:
    picture = np.arange(16 * 16 * 3, dtype=np.uint8).reshape(16, 16, 3)
    frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
    assert (frame.to_ndarray() == picture).all()
