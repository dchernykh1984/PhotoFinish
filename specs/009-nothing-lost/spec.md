# Feature Specification: Nothing the phone kept is lost

**Feature Branch**: `feat/nothing-lost`

**Created**: 2026-11-21

**Status**: Draft

**Input**: Maintainer, 2026-11-21, after two lenses at 2560x1440 and 60 fps fell 48 s behind on a
home Wi-Fi and caught up again: a race may be run in a forest on one old router or a satellite
terminal everybody shares, so the network may be slower than the cameras for a long while. The
picture is never made worse to fit it (no adaptive bitrate: a number must stay readable); what the
network cannot take now comes later. So what the phone keeps must not be lost when the app
crashes, Android kills it, the phone switches off or Stop is tapped: it is sent at the next start,
or after Stop, however long that takes. The store takes the phone's free space less 10 GB. The
first lens catches up first, the others with what the network leaves. The laptop shows how much
the phone still holds for each camera, as a bar, and the phone's free storage, with a warning under
30 GB.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The app or the phone dies, the frames do not (Priority: P1)

The phone streams two lenses behind a slow network, a minute of video kept. Its battery dies (or
the app crashes, or Android kills it). Charged and started again, the app sends what it kept to
the cameras it was going to, before anything new, without Start being tapped; the recording gets
that minute, late, each frame at the moment it was taken and listed once.

**Why this priority**: A rider crossing in that minute is in no other record. A photo finish is
only as good as its worst second, and a dead phone at a cold finish line is not rare.

**Independent Test**: The emulator streams to a recorder that is stopped; the app is killed with
frames kept; the recorder is started, then the app: every frame kept arrives once, at its moment.

**Acceptance Scenarios**:

1. **Given** frames kept and the app killed, **When** the app starts, **Then** they are sent to
   their recorder before any new stream to it, without Start.
2. **Given** the phone switched off as it wrote, **Then** at most the last second written is lost,
   and what was written before is sent.
3. **Given** frames kept whose moments were never known (the clock exchange not through), **Then**
   they are not sent after a restart: placed by their arrival, they would be late by hours.

### User Story 2 - Stop sends what is left (Priority: P1)

The referee taps Stop with three minutes not sent. The cameras stop; the three minutes go on being
sent, with the screen off and the app in the background too, a notification saying how much is
left. Only "Discard unsent" drops them, after a confirmation saying how much video goes.

**Why this priority**: Stop is tapped at the end of a race, exactly when a slow network still owes
the last finishes.

**Independent Test**: Stop with frames kept: they arrive; the notification is there until they
have; Discard, confirmed, empties the store.

**Acceptance Scenarios**:

1. **Given** Stop with frames kept, **Then** they are sent and the recording gets them.
2. **Given** another size or lens chosen, the screen leaving or the app closed, **Then** what the
   streams kept is sent all the same; a new stream to the same camera waits until it has been.
3. **Given** Discard confirmed, **Then** everything kept is dropped and counted as dropped.
4. **Given** sending in the background stopped by Android, **Then** the next start goes on.

### User Story 3 - The first lens catches up first (Priority: P2)

Two lenses behind a network that carries one and a half. The first lens of the code (Main, as the
laptop's dialog orders them) sends while it is behind; the others send what is left, and catch up
once it has.

**Why this priority**: One camera near live and whole beats two behind; the others' frames are
kept, not lost, and come later.

**Independent Test**: With the first lens behind, the others' frames wait on the phone; once it is
within 2 s of live, they flow.

**Acceptance Scenarios**:

1. **Given** the first lens more than 2 s behind and connected, **Then** the others send nothing.
2. **Given** the first lens's camera gone from the laptop (it cannot connect), **Then** the others
   send as if it were not there.

### User Story 4 - The laptop shows what the phone still holds (Priority: P2)

In the camera list, beside "N s behind", the camera's line says how much video the phone still
holds for it, a bar of how much has come since it began falling behind, and when it should be in.
The phone's free storage is shown among its readings: amber under 30 GB, red under 10 GB.

**Why this priority**: The referee decides when to publish results by when the video is in.

**Independent Test**: A phone status with `unsent_ms` and `free` shows the line, the bar and the
reading at their levels.

**Acceptance Scenarios**:

1. **Given** a phone holding 12 minutes for a camera, **Then** its line says so, with a bar.
2. **Given** a phone with 25 GB free, **Then** the reading is amber; with 8 GB, red.

### Edge Cases

- The laptop's camera removed or the laptop gone for good: the phone keeps the frames, tries again
  every few seconds, until Discard or until the space runs out, the oldest giving way.
- The phone paired again with another laptop: what it kept goes to the old address, new frames to
  the new.
- The recorder restarted, or a connection lost, while the kept frames are sent: sent again from
  where the recorder may not have them (007); the recording lists each frame once.
- The phone restarted: the frames' own clock started again too; how long a frame was held is told
  by the phone's wall clock.
- Two copies of the app on one phone are not provided for (`specs/app/README.md`, Known limits).
- The phone short of space: the store keeps what fits above 10 GB free, the last 2 s however short.
- The app updated with frames kept: the new version reads the store and sends them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each stream's frames, their index -- capture time, keyframe, moment, when kept on the
  phone's wall clock -- and what the stream needs to be sent -- its address, format, codec and
  header -- are kept on the phone's storage as they come, a keyframe's run synced to it, so a crash
  costs nothing written and a power cut at most the last second.
- **FR-002**: At the app's start every stream kept is sent to its address, without Start, the
  oldest first for each address, from its oldest frame; frames without a moment are not sent. A
  connection of kept frames says how long its first frame was held, by the wall clock when the
  frames' own clock started again since (contract `held_ms`).
- **FR-003**: Stop, another choice, the screen leaving, the app closing or an encoder failing do
  not drop what a stream kept: it is sent; a new stream to an address waits until the streams
  kept for it are sent, so a camera's frames reach the recorder in the order taken.
- **FR-004**: "Discard unsent" on the phone drops everything kept, after a confirmation that says
  how much video goes; nothing else drops kept frames but the space running out (FR-005).
- **FR-005**: The store takes the phone's free space less 10 GB; beyond it the oldest frames not
  sent give way, counted among the frames dropped; the last 2 s are kept however short of space.
- **FR-006**: While anything is unsent or a lens streams, the app runs a foreground service, its
  notification saying how much video is left to send, so sending goes on with the screen off and
  the app in the background; stopped by Android, the app goes on at its next start (FR-002).
- **FR-007**: The first lens of the code sends first: while it is connected and more than 2 s
  behind, the other lenses' streams send nothing and hold no connection; their frames wait.
- **FR-008**: The status a keyframe carries adds `free`, the phone's free storage in MB, and
  `unsent_ms` and `unsent_mb`, the video the phone holds for the lens's camera, its span in
  milliseconds and its size in MB (contract).
- **FR-009**: The laptop's camera line adds, while the phone holds video for it, "N min M s of video
  on the phone", a bar of how much has come since it began falling behind, and "in about N min"
  once that can be told; the readings add the phone's free storage, amber under 30 GB, red under
  10 GB.
- **FR-010**: The phone's screen shows how much video is unsent, and the Discard button while any
  is.

### Key Entities

- **A kept stream**: a folder on the phone per stream -- lens, address, format, codec, header --
  of keyframe runs, each a file of frames and a file of their index.

## Success Criteria *(mandatory)*

- **SC-001**: The app killed with 30 s kept: after its start, all 30 s are in the recording, each
  frame once, at its moment.
- **SC-002**: Stop with 30 s kept: all 30 s arrive; the notification stays until they have.
- **SC-003**: With the first lens behind, no frame of the others is sent until it is within 2 s.
- **SC-004**: A phone status of 25 GB free shows amber; 12 minutes held shows the line and the bar.

## Assumptions

- The referee keeps the phone on a charger: sending can take hours after a long slow stretch.
- Uninstalling the app or clearing its data drops what it kept, as Android removes its files.
- Android 15 limits a data sync foreground service to 6 hours a day; past it, the app stops the
  service and goes on at its next start.
- What the recorder lists is unchanged: frames it has are listed once (007, FR-007).
