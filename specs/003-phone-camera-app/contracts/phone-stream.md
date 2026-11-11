# Contract: PhotoFinish Camera and the recorder

## Pairing

PhotoFinish shows `rtmp://<this computer>:<port>/<path>` as text and as a QR code holding exactly
that text. The app streams to it and makes the clock exchange with `<this computer>` on `<port>`
over UDP.

With several lenses chosen (`specs/004-phone-lenses`), the code holds one line per lens instead,
`<lens> <address>`, lines separated by `\n`, the lens one of `main`, `ultrawide`, `telephoto` and
`front`; each lens is a camera of its own, on its own port:

```
main rtmp://192.168.31.106:1935/live/cam1
telephoto rtmp://192.168.31.106:1936/live/cam2
```

An address alone is the main lens, so a code of either kind pairs. The app streams each lens it
has to its address and makes the clock exchange with each address's port; a line it cannot read,
or a lens named twice after the first, is left out and said.

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
the start), an older one counted 2 ms longer for each second of its age; it is taken as it
comes over a connection's first 2 s of frames, then followed at 2 ms a second at most; a change
of more than 50 ms is taken at once, and an exchange whose offset the delays cannot explain
(the recorder's clock changed) clears the ones before it. A request of another length or tag
gets no answer, and the recorder answers 50 requests a second at most, from any sender.

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

## The phone's status (H.264 SEI, `specs/005-phone-status`)

Each keyframe -- one a second -- carries, after the frame's moment, a second SEI NAL unit with one
`user_data_unregistered` message:

| Bytes | Field |
| --- | --- |
| 0-15 | UUID `e1a46cea-b5ff-4c7d-b445-4c7dbd7ea281` |
| 16-19 | `PFS1` |
| 20- | the readings, ASCII: `key=value` pairs separated by `;` |

| Key | Value |
| --- | --- |
| `battery` | percent, 0-100 |
| `charging` | `1` or `0` |
| `temp` | the battery's temperature, degrees C, one decimal |
| `thermal` | Android's thermal status, 0 (none) to 6 (shutdown) |
| `saver` | power saver on, `1` or `0` |
| `wifi` | the Wi-Fi signal, dBm |
| `dropped` | the frames the uplink dropped for the network in the last minute |

A reading the phone cannot tell is left out; a key the recorder does not know is kept and not
shown. The message's size is written as SEI sizes are (a 255 for each full 255).

## The stream (RTMP)

Plain RTMP as FFmpeg's listener takes it: the simple handshake, `connect` with the path's first
part as the application, `releaseStream`, `FCPublish`, `createStream`, `publish` with the rest as
the stream name, then `@setDataFrame`/`onMetaData` (width, height, frame rate, video codec 7, no
audio), the AVC sequence header and the frames. Chunk size 65536. Timestamps are milliseconds from
the connection's first frame; from 0xFFFFFF on they are sent as extended timestamps.
