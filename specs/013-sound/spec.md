# Feature Specification: Sound

**Feature Branch**: `feat/sound-and-speed`

**Created**: 2026-11-21

**Status**: Draft

**Input**: Maintainer, 2026-11-21: only video is sent and recorded. Sound is wanted in the
program and in the exported file: at the start one sometimes needs to listen; someone shouting
"hurray, Vasya" as two riders finish tells that Vasya was one of them; numbers dictated, the
starting pistol. Sound is sent as video is: kept on the phone, sent from the oldest not sent.
The main lens's video goes first, then the sound, then the other lenses' video. Asked: forwards
at any speed with the voice's pitch kept, silent backwards; no sound while Live.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Hear what was said at the line (Priority: P1)

Two riders finish together; the referee plays the seconds around the line and hears a spectator
shout a name, or a marshal call the numbers, at x1 or slowed, the voice at its own pitch.

**Why this priority**: what was said or heard at the line is evidence no frame shows.

**Independent Test**: A phone streams a tone that starts at a flash; played back, the tone is
heard as the flash is shown, within a tenth of a second, at x1 and at x0.5.

**Acceptance Scenarios**:

1. **Given** a recording with sound, **When** the referee presses "Play >", **Then** the chosen
   camera's sound plays with it; at x0.5 slower, its pitch the same.
2. **Given** playing backwards, stepping, or Live, **Then** no sound.
3. **Given** the sound switch off, **Then** playing is silent, the recording unchanged.

### User Story 2 - Sound through a break (Priority: P1)

The Wi-Fi drops for a minute; the phone keeps the sound with the video and sends both once it
can, oldest first; nothing said at the line is lost.

**Why this priority**: the same promise as the video's (`specs/009-nothing-lost`).

**Independent Test**: The recorder stopped for 30 s, then started again: the sound of those 30 s
is in the recording, once.

**Acceptance Scenarios**:

1. **Given** a break, **Then** the sound is kept and sent with the main lens's video, in time
   order, before any other lens's video.
2. **Given** the phone sends again what a lost connection may have swallowed, **Then** that
   stretch's sound is recorded once.

### User Story 3 - The exported file has sound (Priority: P2)

"Export video..." writes each camera's MP4 with its phone's sound in step with the picture.

**Independent Test**: An exported file of a recording with a tone at a flash plays the tone at
the flash in QuickTime.

### Edge Cases

- The microphone not allowed on the phone: video only, the phone saying so on its screen and in
  its log, which the laptop shows.
- A streaming app that sends sound (Larix): recorded and played the same way; one without, none.
- A phone with several lenses sends its sound once, with its main lens; another lens of the same
  phone plays and exports that sound.
- The main lens's camera lost a moment: the sound goes on, kept and sent with the main lens.
- USB cameras, files played as live, the test camera and a camera's own file opened as it is:
  no sound, as today.
- A gap in the sound is silence of its length, the sound after it in step again.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: PhotoFinish Camera records the phone's microphone while its main lens streams --
  AAC, mono, 48 kHz where the phone takes it --, each piece stamped on the clock its frames are
  stamped on, and asks for the microphone once; refused, it streams video alone and says so.
- **FR-002**: The sound is kept on the phone with the main lens's frames, in the order captured,
  and sent with them on the main lens's connection, oldest first: through breaks, restarts and
  Stop as its video is (`specs/009-nothing-lost`); the other lenses wait for the main lens, sound
  included, as they wait for it now.
- **FR-003**: The recorder keeps a stream's sound in the segments beside its video, each piece
  placed by the video's moments, and each stretch once though sent again.
- **FR-004**: The window plays the sound of the camera shown, or of its phone's main lens, while
  playing forwards at any speed, the pitch kept; silent backwards, stepping, paused and Live; a
  "Sound" switch beside the speeds, remembered with the session.
- **FR-005**: An exported MP4 carries the camera's sound -- or its phone's main lens's -- in step
  with the picture.
- **FR-006**: Played sound and picture agree within 100 ms; a gap is silence of its length.

## Success Criteria *(mandatory)*

- **SC-001**: A tone that starts at a flash is heard within 100 ms of the flash, played and
  exported.
- **SC-002**: 30 s of break cost no sound: sent after it, recorded once.
- **SC-003**: The sound adds under 1% to a lens's bitrate (128 kbit/s against 16 Mbit/s).

## Assumptions

- The sound rides the main lens's connection, its 1% shared with that lens's video: it is never
  behind the other lenses' video, and the main lens's video loses a hundredth of its share.
- AAC at 128 kbit/s mono: speech and a pistol clear; stereo tells nothing more at a finish line.
- The sound's moments come from the video's: the recorder places a piece by the frame beside it,
  as both are stamped on one clock in one connection.
