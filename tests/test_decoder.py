"""The frames decoded lately kept, so a step back is not a decode from the keyframe
(specs/012, FR-005)."""

from __future__ import annotations

from pathlib import Path

from app.decoder import Decoder
from app.recorder.testcam import read_time
from app.video_index import VideoIndex
from tests.test_video_index import START, record


def frames(tmp_path: Path, count: int = 30) -> VideoIndex:
    record(tmp_path, START, count)  # mpeg4, a keyframe every 15 frames
    index = VideoIndex(tmp_path)
    index.refresh()
    return index


def shows(decoder: Decoder, index: VideoIndex, place: int) -> bool:
    frame = index.frame(place)
    decoded = decoder.decode(frame.path, frame.pts)
    return (
        decoded is not None
        and read_time(decoded.to_ndarray(format="rgb24")) == frame.ms
    )


def test_stepping_back_takes_the_frames_decoded_on_the_way(tmp_path: Path) -> None:
    index = frames(tmp_path)
    decoder = Decoder()
    assert shows(decoder, index, 14)  # decoded from the keyframe at 0
    assert decoder.seeks == 1
    assert all(shows(decoder, index, place) for place in range(13, -1, -1))
    assert decoder.seeks == 1  # every one of them kept on the way
    decoder.close()


def test_frames_played_forwards_are_kept_for_a_step_back(tmp_path: Path) -> None:
    index = frames(tmp_path)
    decoder = Decoder()
    assert all(shows(decoder, index, place) for place in range(10))
    assert shows(decoder, index, 4)
    assert decoder.seeks == 1
    decoder.close()


def test_the_frames_kept_are_bounded_by_their_size(tmp_path: Path) -> None:
    index = frames(tmp_path)
    one = 640 * 360 * 3 // 2  # a 640x360 frame in yuv420p
    decoder = Decoder(keep_bytes=4 * one)
    assert shows(decoder, index, 14)
    assert shows(decoder, index, 11)  # among the last four decoded
    assert decoder.seeks == 1
    assert shows(decoder, index, 9)  # not kept: decoded again from the keyframe
    assert decoder.seeks == 2
    decoder.close()


def test_a_frame_looked_at_again_is_kept_before_older_ones(tmp_path: Path) -> None:
    # Stepping back and forth around a crossing: the frame looked at lately stays,
    # the one decoded first and not looked at since goes.
    index = frames(tmp_path)
    one = 640 * 360 * 3 // 2
    decoder = Decoder(keep_bytes=4 * one)
    assert all(shows(decoder, index, place) for place in range(4))  # 0 to 3 kept
    assert shows(decoder, index, 0)  # looked at again
    assert shows(decoder, index, 4)  # one more decoded: 1 goes, not 0
    seeks = decoder.seeks
    assert shows(decoder, index, 0)
    assert decoder.seeks == seeks
    decoder.close()


def test_another_segment_lets_the_frames_kept_go(tmp_path: Path) -> None:
    index = frames(tmp_path, 60)  # two segments
    first, second = index.frame(5), index.frame(40)
    assert first.path != second.path
    decoder = Decoder()
    assert shows(decoder, index, 5)
    assert shows(decoder, index, 40)
    assert decoder.seeks == 2
    assert shows(decoder, index, 4)  # its segment's frames gone with it
    assert decoder.seeks == 3
    decoder.close()
    assert decoder.kept == 0
