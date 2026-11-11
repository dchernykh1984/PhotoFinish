# Feature Specification: A network break costs no frame

**Feature Branch**: `feat/store-and-forward`

**Created**: 2026-11-11

**Status**: Draft

**Input**: Maintainer, 2026-11-11, after trying 0.6.0 on the Xiaomi 17 Ultra: when the video
stream breaks because of the network -- not because Stop was tapped on the phone -- the stream
should be kept somewhere and sent to the laptop once the connection is back. In the same pull
request, the other problems the try showed: four lenses asked for, the phone's camera failed and
the app stopped for good with the lenses' lines still saying "connecting again"; the 0.6.0 window
went on using the recorder 0.5.0 had started, so the phone's status and lenses never showed; the
front lens the phone cannot stream beside the others kept the banner red.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A network break costs no frame (Priority: P1)

The phone streams; the Wi-Fi drops for 20 s and comes back. Meanwhile the phone keeps every frame
of every lens on its own storage. Once connected again it sends the kept frames first, then the
live ones, and the recording has every frame of those 20 s at the moments they were taken. The
laptop's live picture is behind for as long as the phone needs to catch up, and the camera's line
says by how much.

**Why this priority**: A rider crossing the line during a break was lost before: the recording
showed a gap. A photo finish is only as good as its worst second.

**Independent Test**: The emulator streams to a recorder; the recorder is killed and started again
after 10 s; the recording has the frames of those 10 s, each once, and no gap is noted for them.

**Acceptance Scenarios**:

1. **Given** a 20 s break, **Then** the recording has the break's frames at their own moments and
   `gaps.txt` notes no gap for it.
2. **Given** frames sent in the last seconds before the break never arrived -- lost in the dead
   connection --, **Then** they are sent again, and the recording lists each frame once.
3. **Given** the phone catching up, **Then** the camera's line says how many seconds behind live
   it is, until it is live again.
4. **Given** Stop tapped on the phone, **Then** what it kept is dropped and streaming ends, as
   before.
5. **Given** a break longer than the phone can keep, **Then** the oldest kept frames give way,
   counted among the frames the phone dropped, and the recording shows a gap for them alone.

### User Story 2 - The phone streams again after its camera failed (Priority: P1)

With several lenses, the phone's camera failed and the app's next try to open it threw; the app
then stopped for good, and the lenses' lines still said "Connection lost ... connecting again".
Now an open that throws is tried again a moment later, as a camera lost while streaming is, and
the lenses' lines say their streams stopped with the camera.

**Why this priority**: At a race nobody watches the phone at the finish line; a camera that stops
for good stops the photo finish.

**Independent Test**: A JVM test whose camera open throws sees the open tried again; the lens lines
say the streams stopped.

**Acceptance Scenarios**:

1. **Given** opening the camera throws, **Then** the screen says why and that it tries again, and
   it does, every 2 s, until it opens or Stop is tapped.
2. **Given** the camera failed with lenses streaming, **Then** no lens line keeps a connection's
   last words.

### User Story 3 - An updated PhotoFinish records with its own recorder (Priority: P2)

A recorder outlives the window, so an update left 0.5.0's recorder running under the 0.6.0 window:
the phone's status and its lenses never showed. The window that finds a recorder of another
version running replaces it with its own, and says so.

**Why this priority**: The referee updates between races and expects what the update brings;
nothing on the screen said an old recorder was at work.

**Independent Test**: A heartbeat of another version, or of none, makes the window's watchdog stop
that recorder and start its own once it has ended.

**Acceptance Scenarios**:

1. **Given** a recorder whose heartbeat names another version, or none, **Then** the window stops
   it, starts its own once it has ended, and the camera's line says the recorder is being replaced.
2. **Given** a recorder of the window's own version, **Then** the window attaches to it, as before.

### User Story 4 - A lens the phone leaves out does not hold the banner red (Priority: P3)

Four lenses were asked for; the phone streams three and says it cannot run the front one beside
them. The front camera's line says the phone leaves it out, amber, and RECORDING stays green while
the other three record.

**Independent Test**: A Qt test with three lenses recording, their status listing `front` as left
out, shows the front camera as left out and the banner green.

**Acceptance Scenarios**:

1. **Given** a lens camera whose phone's status lists its lens as left out, **Then** its line says
   so in amber and it does not turn the banner red.
2. **Given** a camera added before this change (no lens noted), **Then** it shows as before.

### Edge Cases

- The recorder restarted -- an update (User Story 3), a crash -- is a break like any other to the
  phone: it keeps the frames and sends them to the new recorder.
- The clock exchange is lost during the break: frames keep the moments the phone gave them when it
  kept them.
- A network slower than the stream: the phone keeps what the network cannot take instead of
  dropping it, the laptop falls behind live and says by how much; a smaller picture size brings it
  back.
- Several lenses: each keeps and sends its own frames on its own connection; one catching up does
  not hold the others back.
- The phone's storage nearly full: the store stays within its share and leaves 1 GB free.
- An older PhotoFinish (0.6.0 and before) receiving kept frames does not believe their moments and
  places them by their arrival, as it places any frame it cannot believe.
- The app killed or closed during a break: what it kept is gone; it is not sent at the next Start.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: PhotoFinish Camera keeps each lens's encoded frames, with their moments, in a store
  on its own storage, oldest first, until they are sent; a frame sent is kept 6 s more. The uplink
  takes its frames from the store, so a break, a slow network or a recorder restarting costs no
  frame while the store has room.
- **FR-002**: A connection made after a loss begins at the last keyframe at least 6 s before the
  loss was noticed -- what a dead connection may have swallowed -- and goes on through the kept
  frames to the live ones, as fast as the network takes them.
- **FR-003**: The store holds at most 2 GB for all the lenses, and less if the phone would keep
  under 1 GB free; when it is full, the oldest unsent frames give way, up to the next keyframe, and
  are counted among the frames dropped (`specs/005-phone-status`, `dropped`).
- **FR-004**: Stop empties the store, and so does the app's start (what a killed app left).
- **FR-005**: Each connection's metadata says how long its first frame was kept, `held_ms`
  (contract).
- **FR-006**: The recorder believes a phone's frame moment up to `held_ms` older than it would
  otherwise (5 s).
- **FR-007**: The recorder writes a frame whose moment is at or before the newest it recorded in
  this run -- one sent again -- into the segment, for the frames after it to decode, and leaves it
  out of the segment's frame times, so the recording lists each frame once.
- **FR-008**: The recorder's heartbeat says how far its newest frame is behind its clock; the
  camera's line says "N s behind" while it is 2 s or more.
- **FR-009**: The recorder writes its PhotoFinish version into its heartbeat. The window that
  finds a recorder of another version, or of none, running stops it and starts its own once it has
  ended, the camera's line saying so meanwhile.
- **FR-010**: An open of the camera that throws is tried again after 2 s, as a camera lost while
  streaming is; the screen says the reason and that it tries again.
- **FR-011**: When the camera stops -- lost, failed, closed -- each of its lenses' lines says its
  stream stopped with the camera; a connection's later words are not shown.
- **FR-012**: The cameras the add-camera dialog makes for a phone's lenses note their lens and
  their phone. A lens camera whose phone's status (any of its lenses') lists its lens as left out
  shows "the phone leaves this lens out" in amber and does not count against RECORDING.
- **FR-013**: Covered by automated tests: the store, the resend and the order of frames (JVM); the
  moments believed, a frame sent again written and not listed, the heartbeat's lag and version
  (pytest); the watchdog's replacement, the lag and the left-out lens in the window (Qt tests).

## Success Criteria *(mandatory)*

- **SC-001**: With the emulator streaming at 30 fps, the recorder killed and started again after
  10 s: the recording has 300 frames or more in those 10 s, no frame listed twice, no gap noted.
- **SC-002**: After that break, the camera is live again -- less than 1 s behind -- within 10 s.
- **SC-003**: With a 0.6.0 recorder running, the window replaces it within 5 s, and the phone's
  status shows once the phone streams to the new one.

## Assumptions

- Stop is the referee's word that the stream is over: nothing kept is sent after it.
- 6 s covers what a dead connection may have taken: a send hangs 5 s before the uplink gives the
  connection up, and keyframes come every second.
- The store is the app's own, not shared with other apps; the space it takes is its while the
  phone streams.
- What took the Xiaomi 17 Ultra's camera down with four lenses at 2560x1440 and 60 fps is looked
  into with the phone's log; what it shows may join this change.
