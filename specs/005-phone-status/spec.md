# Feature Specification: What may stop a phone's stream, shown on the laptop

**Feature Branch**: `docs/release-pr-pipeline` (PR #20, at the maintainer's word)

**Created**: 2026-11-11

**Status**: Draft

**Input**: Maintainer, 2026-11-11: the program on the laptop must show the phone's battery level,
and any other reading that may switch the phone off or stop its video unexpectedly, near the large
recording indicator, as smaller icons.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The referee sees what may stop a phone before it does (Priority: P1)

Next to the large RECORDING, a line per phone running PhotoFinish Camera shows its battery
(charging or not), how hot it is, its Wi-Fi signal, its power saver and the frames it had to drop
for the network -- each as a small icon and a number, amber when it is worth a look, red when the
stream is at risk. Once a phone stops sending, its last readings stay, marked as such, with when
they came.

**Why this priority**: A phone that goes flat or overheats stops the video in the middle of a
race; the referee, busy with the crossings, must see it coming on the laptop, not on the phone at
the finish line.

**Independent Test**: A stream carrying a status line is recorded; the recorder's heartbeat holds
the readings; the window shows them with the levels the thresholds give.

**Acceptance Scenarios**:

1. **Given** a phone at 57 % and charging, Wi-Fi at -61 dBm, cool, **Then** its line reads the
   battery with a charging mark and the signal, nothing amber or red.
2. **Given** the battery at 9 % and not charging, **Then** the battery reading is red.
3. **Given** the phone's thermal status severe or worse, or its battery at 45 degrees C or more,
   **Then** the heat reading is red; moderate, or 40 degrees and more, amber.
4. **Given** the phone stopped sending, **Then** its line stays, greyed, with the time of its
   last readings.
5. **Given** a camera other than PhotoFinish Camera, **Then** it has no line.

### Edge Cases

- An older PhotoFinish reading a newer phone's stream: the status is an SEI it skips; the frames'
  moments are read as before.
- A phone that cannot tell a reading (no Wi-Fi when it is the hotspot itself, no thermal status
  before Android 10): the reading is left out, not shown as zero.
- Several lenses of one phone: each lens's stream carries the status; each camera shows it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: PhotoFinish Camera writes, once a second with each keyframe, a status into the frame:
  an SEI after the frame's moment (contract), holding battery percent, charging, battery
  temperature, thermal status (Android 10), power saver, Wi-Fi signal and the frames its uplink
  dropped for the network in the last minute; a reading it cannot tell is left out.
- **FR-002**: The recorder reads the status from a phone's keyframes and keeps the last one in its
  heartbeat with the moment it came, through reconnects.
- **FR-003**: The window shows, under the recording banner, a line per camera with a status: the
  camera's name, then small icons with the readings -- battery (with a charging mark), heat, Wi-Fi,
  power saver, dropped frames. Amber: battery 25 % or less and not charging, thermal status
  moderate, battery 40 degrees C or more, Wi-Fi -70 dBm or weaker, power saver on, frames dropped.
  Red: battery 10 % or less and not charging, thermal status severe or worse, battery 45 degrees C
  or more, Wi-Fi -80 dBm or weaker. A status older than 5 s is greyed, with its time.
- **FR-004**: Covered by automated tests: the status written and read (JVM, pytest), the levels,
  the heartbeat, the window's line (Qt test).

## Success Criteria *(mandatory)*

- **SC-001**: On the emulator, the window shows the emulator's battery and its charging within
  seconds of the stream starting.
- **SC-002**: A battery set low on the emulator (`adb emu power capacity 9`, `power ac off`) turns
  the reading red within seconds.

## Assumptions

- Battery, charging and temperature come from Android's battery broadcast; the thermal status from
  `PowerManager` (Android 10); the Wi-Fi signal from the active network's capabilities (Android 10)
  or the Wi-Fi manager.
- The status rides the video: a phone whose stream is down cannot be heard; its last readings are
  what the referee has, and the banner already says the stream is lost.
