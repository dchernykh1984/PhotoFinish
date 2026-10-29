"""The video libraries the live editor builds on, and what it needs from them."""

from __future__ import annotations

import sys

import av
import numpy as np


def test_the_recorder_s_encoder_and_container_are_there() -> None:
    assert "mpeg4" in av.codecs_available
    assert "matroska" in av.formats_available


def test_the_network_cameras_inputs_are_there() -> None:
    # RTSP for the SJCAM HD1080P over Wi-Fi; FLV is RTMP's container (SJ10 Pro).
    assert {"rtsp", "flv"} <= av.formats_available


def test_this_platform_s_usb_capture_is_there() -> None:
    wanted = {"darwin": {"avfoundation"}, "win32": {"dshow"}}.get(
        sys.platform, {"video4linux2", "v4l2"}
    )
    assert wanted & av.formats_available


def test_a_frame_goes_to_numpy_and_back() -> None:
    picture = np.arange(16 * 16 * 3, dtype=np.uint8).reshape(16, 16, 3)
    frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
    assert (frame.to_ndarray() == picture).all()
