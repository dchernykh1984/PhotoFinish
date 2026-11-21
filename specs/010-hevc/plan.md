# Implementation Plan: H.265, as an experiment

**Spec**: [spec.md](spec.md) | **Contract**: [../003-phone-camera-app/contracts/phone-stream.md](../003-phone-camera-app/contracts/phone-stream.md)

## Shape

```
app/widgets/camera_dialog.py      the codec row; the choice in the camera's settings
app/cameras.py                    pairing_text: the `codec h265` line
app/recorder/frame_time.py        SEI read from H.265 units as from H.264
app/recorder/sources.py           an H.265 push read for its moments and status
android/.../pairing/Pairing.kt    the codec line
android/.../capture/FormatChoice.kt  the codec in the format; 0.7 of the bitrate for H.265
android/.../capture/LensStream.kt the encoder by codec; its header from VPS, SPS, PPS
android/.../stream/Hevc.kt        the HEVCDecoderConfigurationRecord from the encoder's units
android/.../stream/Sei.kt         prefix SEI units for H.265
android/.../stream/RtmpPublisher.kt  Enhanced RTMP tags for H.265
android/.../stream/Uplink.kt      the codec's SEI and metadata
```

- **The codec is part of the format**: `StreamFormat.codec`, so a stream kept across opens (007,
  FR-014) is fed again only at the same codec, and the store's header (009) keeps it.
- **The record**: the encoder's csd-0 holds VPS, SPS and PPS; the record's profile, tier, level and
  flags are read from the SPS's profile_tier_level (its first 12 bytes after the header, emulation
  prevention removed); chroma 4:2:0, 8 bits, as phone encoders give.
- **Enhanced RTMP**: a video tag's first byte is 0x80 | frame type << 4 | packet type, then
  `hvc1`: packet type 0 with the record, 3 (CodedFramesX) with the frame's units, each after its
  length in 4 bytes. `onMetaData`'s `videocodecid` is the FourCC as a number.

## Tests

The codec line both ways; frame_time on H.265 units; the dialog's choice and its code; the
phone's format choice and bitrate; the record from known units; the tags' bytes; the SEI units.
On the emulator: H.265 to a recorder, every frame with its moment, frames decoded.
