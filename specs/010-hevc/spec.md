# Feature Specification: H.265, as an experiment

**Feature Branch**: `feat/nothing-lost`

**Created**: 2026-11-21

**Status**: Draft

**Input**: Maintainer, 2026-11-21: two lenses at 2560x1440 and 60 fps take about 40 Mbit/s, more
than a race's Wi-Fi may carry, and the picture must not be made worse to fit (a number must stay
readable). H.265 gives the same picture at a smaller bitrate: offer it as an experimental choice
when the camera is added on the laptop, H.264 staying the default. The Xiaomi 17 Ultra may run two
such encoders; the Xiaomi 11 Ultra, whose processor runs hot, may not or may slow down -- the
maintainer tries them.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - H.265 chosen on the laptop (Priority: P1)

Adding a PhotoFinish Camera camera, the referee picks "H.265 (experimental)". The phone scanning the
code streams H.265 at about 0.7 of the bitrate H.264 takes for the same size and rate; the laptop
records it, every frame at its moment, the phone's status and its log as with H.264, and the window
shows its frames.

**Why this priority**: a third less on the network for the same picture is a third more of the
race sent as it happens.

**Independent Test**: The emulator streams H.265 to a recorder: segments of H.265, every frame with
its own moment, the window decoding them.

**Acceptance Scenarios**:

1. **Given** H.265 chosen, **Then** the code holds `codec h265` and the phone streams H.265.
2. **Given** H.265 streamed, **Then** each frame's moment and each keyframe's status are read as
   from H.264.
3. **Given** H.264 (the default), **Then** nothing changes.

### User Story 2 - A phone that cannot (Priority: P2)

A phone whose encoder does not take H.265 at the size and rate chosen streams H.264, and says so on
its screen and in its log.

**Acceptance Scenarios**:

1. **Given** no H.265 encoder for the format, **Then** H.264, said.

### Edge Cases

- A phone app older than this reads `codec h265` as a line it cannot read, says so and streams
  H.264: the laptop records either.
- Frames kept for sending later (`specs/009-nothing-lost`) keep their codec.
- A video exported from the recording (`specs/011-video-export`) is H.265 too.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The camera dialog offers, for PhotoFinish Camera, H.264 (the default) or H.265
  (experimental); the camera keeps the choice; the code adds a line `codec h265` for it, the main
  lens alone keeping its address alone on the first line.
- **FR-002**: The phone reads the line: with H.265, it encodes H.265 when its encoder takes the size
  and rate chosen, at 0.7 of H.264's bitrate for them; else H.264, said on its screen and in its log.
- **FR-003**: H.265 goes over Enhanced RTMP (FourCC `hvc1`): the sequence start carries the
  HEVCDecoderConfigurationRecord, frames go without a composition time; each frame's moment and each
  keyframe's status are the same SEI messages in prefix SEI units (contract).
- **FR-004**: The recorder reads H.265 as it reads H.264: moments, status, segments kept as they
  came; the window decodes them.

## Success Criteria *(mandatory)*

- **SC-001**: On the emulator, an H.265 stream is recorded with every frame at its own moment, and
  the window shows its frames.
- **SC-002**: H.265's bitrate for 2560x1440 at 60 fps is 11.2 Mbit/s against H.264's 16.

## Assumptions

- FFmpeg reads Enhanced RTMP's H.265 (since 6.1; PyAV 19 carries a newer one).
- H.265 gives H.264's picture at 50 to 70% of its bitrate; 0.7 keeps to the safe side. The
  maintainer judges the picture on the phones.
