# Feature Specification: A camera's video as one file

**Feature Branch**: `feat/nothing-lost`

**Created**: 2026-11-21

**Status**: Draft

**Input**: Maintainer, 2026-11-21: the video is kept in one-second pieces; a button in the
desktop program, where it fits, exports it as one file -- a file per camera, several files for
several cameras.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Export the race's video (Priority: P1)

After the race the referee wants a camera's video to show or keep: "Export video..." under the
cameras lists them, all ticked; the referee picks a folder; each camera ticked becomes one MP4,
named after it, which any player opens. Hours of video export in the background, a progress bar
showing, Cancel stopping it.

**Why this priority**: the pieces serve the program; a protest, a sponsor or the archive needs
a file.

**Independent Test**: A recording of 70 frames exports to one MP4 of 70 frames, its times stepping
as the frames' moments do.

**Acceptance Scenarios**:

1. **Given** two cameras ticked and a folder, **Then** two MP4 files there, one per camera.
2. **Given** a file of that name there, **Then** the new one gets a number; nothing is overwritten.
3. **Given** Cancel, **Then** the file being written is removed; those done stay.

### Edge Cases

- A camera recording meanwhile is exported up to the last piece closed when the export began.
- A frame the phone sent again (`specs/007-store-and-forward`) is in the file once.
- The stream's format changed within the recording -- another size, codec or header, the phone set
  up again --: the file goes on as `<name>-2.mp4`, as one file holds one format.
- A gap in the recording is a gap in the file: the frame before it stays on screen.
- A camera that only opened a video file as it is has nothing to export: it is not listed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: "Export video..." in the cameras box lists the cameras with a recording, all ticked;
  the referee picks a folder; each camera ticked is written there as `<camera name>.mp4`, a number
  added when that name is taken.
- **FR-002**: The frames are copied as recorded, not encoded again: the picture is the recording's,
  in the order and at the moments listed, each frame once, from the first keyframe.
- **FR-003**: Where the stream's format changes, the camera's file ends and `<name>-2.mp4` (then
  `-3`) goes on.
- **FR-004**: A file's time begins at its first frame's moment, its creation time that moment;
  H.265 is tagged `hvc1`, as QuickTime wants it.
- **FR-005**: The export runs in the background with a progress of the pieces done; Cancel stops it
  and removes the file under way; the recording is only read.

## Success Criteria *(mandatory)*

- **SC-001**: 70 frames recorded export to one MP4 of 70 frames, their times those of the moments.
- **SC-002**: Two formats in one recording export to two files.

## Assumptions

- MP4 over Matroska: QuickTime and the phones' players open it; the pieces stay Matroska, as a
  killed recorder loses least that way.
