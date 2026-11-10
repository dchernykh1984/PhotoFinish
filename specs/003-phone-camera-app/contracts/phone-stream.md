# Contract: PhotoFinish Camera and the recorder

## Pairing

PhotoFinish shows `rtmp://<this computer>:<port>/<path>` as text and as a QR code holding exactly
that text. The app streams to it and makes the clock exchange with `<this computer>` on `<port>`
over UDP.

## The clock exchange (UDP, the RTMP port number)

All integers are big-endian. Times are microseconds.

Request, 13 bytes:

| Bytes | Field |
| --- | --- |
| 0-3 | `PFTS` |
| 4 | version, 1 |
| 5-12 | `t1`: the phone's camera clock when sent |

Answer, 29 bytes:

| Bytes | Field |
| --- | --- |
| 0-3 | `PFTS` |
| 4 | version, 1 |
| 5-12 | `t1`, as received |
| 13-20 | `t2`: the recorder's clock, Unix microseconds, when the request arrived |
| 21-28 | `t3`: the recorder's clock when the answer left |

The phone notes `t4`, its clock when the answer arrived, and keeps for each exchange
`offset = ((t2 - t1) + (t3 - t4)) / 2` and `delay = (t4 - t1) - (t3 - t2)`. The offset it uses
follows the one of the shortest delay among the last 8 exchanges, made every 2 s (5 at once at
the start), at 2 ms a second at most; a change of more than 50 ms is taken at once, and an
exchange whose offset the delays cannot explain (the recorder's clock changed) clears the ones
before it. A request of another length or tag gets no answer.

## The frame moment (H.264 SEI)

Each frame of a connection made once the app has an offset begins with an SEI NAL unit (type 6)
holding one
`user_data_unregistered` message (payload type 5):

| Bytes | Field |
| --- | --- |
| 0-15 | UUID `e1a46cea-b5ff-4c7d-b445-4c7dbd7ea281` |
| 16-19 | `PFT1` |
| 20-27 | the frame's capture moment: Unix microseconds on the recorder's clock |

The NAL unit carries emulation-prevention bytes as H.264 requires. The recorder reads it from the
packet as the RTMP demuxer gives it (length-prefixed NAL units), takes the moment rounded to the
millisecond as the frame's moment, and stores the packet unchanged: the SEI stays in the recording,
and decoders ignore it.

## The stream (RTMP)

Plain RTMP as FFmpeg's listener takes it: the simple handshake, `connect` with the path's first
part as the application, `releaseStream`, `FCPublish`, `createStream`, `publish` with the rest as
the stream name, then `@setDataFrame`/`onMetaData` (width, height, frame rate, video codec 7, no
audio), the AVC sequence header and the frames. Chunk size 65536. Timestamps are milliseconds from
the connection's first frame; from 0xFFFFFF on they are sent as extended timestamps.
