# Feature Specification: What the phone hits, on the laptop

**Feature Branch**: `feat/phone-log`

**Created**: 2026-11-17

**Status**: Draft

**Input**: Maintainer, 2026-11-17, after 0.7.0 on the Xiaomi 17 Ultra with four lenses at 2560x1440
and 60 fps: the laptop said only that each lens's connection broke (`[Errno 5] Input/output error`),
the phone's own words were on its screen at the finish line, and the cause needed the phone on a
USB cable. "Add a stream of errors to the phone app and send it to the laptop on a stream of its
own: then all the errors can be seen, and diagnostics added."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The phone's errors reach the laptop (Priority: P1)

The phone streams four lenses; its camera fails and the app opens it again and again. On the
laptop, each lens camera's folder holds the phone's log: when the app started and on what phone,
the cameras and sizes it opened, the camera's error codes with what they mean, the exceptions it
caught, the warnings the phone's camera and encoder services gave it, each connection lost and
why -- seconds after they happen. Whoever looks into the failure reads the file instead of
fetching the phone.

**Why this priority**: A failure on the phone was seen on the phone alone, and its cause needed a
cable and a computer beside the phone; at a race the phone is at the finish line.

**Independent Test**: The emulator streams to a recorder; its log is in the camera's folder,
the app's start first; a recorder stopped meanwhile gets the lines it missed once it is back.

**Acceptance Scenarios**:

1. **Given** the app is open and paired, streaming or not, **Then** its log reaches the recorder of
   each lens it is paired with, within 2 s of each line, and is kept in `phone.log` in the
   camera's folder.
2. **Given** the network or the recorder is down, **Then** the phone keeps its last 1,000 lines and
   sends them once the recorder answers again; lines it could no longer keep are said lost.
3. **Given** the app ended on an error it did not catch, **Then** its next start sends that error
   first.
4. **Given** the app is started again, **Then** the log says so and goes on in the same file.

### User Story 2 - The referee sees why a phone gives no video (Priority: P2)

A lens camera that does not record shows, after what its recorder says, the last error or warning
its phone sent: "the phone: camera error 4 -- the camera device failed".

**Why this priority**: The referee looks at the laptop, not at the phone; "Input/output error"
does not tell them to choose fewer lenses or a smaller picture.

**Independent Test**: A Qt test whose heartbeat holds the phone's last error shows it in the line
of a camera that does not record, and not in one that records.

**Acceptance Scenarios**:

1. **Given** a camera not recording whose phone said an error, nothing since, **Then** its line ends
   with the phone's words -- how long ago they came, past a minute.
2. **Given** an error of one lens, **Then** the other lenses' lines do not show it; an error of the
   phone as a whole shows on each.
3. **Given** the camera records, **Then** its line is as before.

### Edge Cases

- A line longer than the network takes in one message is cut, and says so.
- A phone saying much in a burst: at most 20 lines a second are kept, and how many were left out
  is said.
- An older PhotoFinish receiving the log answers nothing; the phone keeps its lines and tries
  again, slower, and the video is as before.
- An older PhotoFinish Camera sends no log; nothing changes.
- Several lenses: each lens's recorder keeps the whole log; a lens's line on the laptop shows the
  phone's words of that lens and of the phone as a whole.
- The phone's log is no stream of video: nothing of it goes into the recording, and a recorder
  that cannot write it records on.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: PhotoFinish Camera keeps a log of what it meets: its start (version, phone, Android),
  each camera and lens it opens at what size and rate, every status its screen shows of the
  cameras and of each lens -- once, when it changes, one said again within a minute counted and
  told with its next time, and where a lens comes to rest told within 5 s --, the camera's error codes with their meaning, the exceptions it catches with where they were thrown -- its own lines said again within a minute counted likewise --, the warnings and errors its own
  process writes to the system log (the camera and encoder services' words to it), and an error
  that ended the app, from its next start.
- **FR-002**: The log is sent to the recorder of each lens the app is paired with, on the port its
  clock exchange uses (contract), whether it streams or not; each recorder answers with the newest
  line it has kept, and the phone sends again what was not answered.
- **FR-003**: The phone keeps its last 1,000 lines for recorders that did not answer, the system
  log's going first; at most 20 of the system log's lines a second, the number left out said once
  their second is over; a line is at most 400 bytes.
- **FR-004**: The recorder keeps the phone's lines in `phone.log` in the camera's folder, in the
  order the phone wrote them, each once, with the phone's time, its level and its lens -- the last
  few runs each going on where it was, two phones given one code too; a new start of the app and
  lines the phone no longer kept said there. It writes them on a thread of its own: the clock
  exchange is never held back by the file. Over 10 MB the file is kept as `phone.log.1`
  and a new one begun.
- **FR-005**: The recorder's heartbeat holds the last error or warning of the camera's lens, or of
  the phone as a whole -- till another comes; the retry's own lines end none --, with how long ago
  the phone said it, by the phone's own clock; the log's notes about itself are none of it; the window shows it after the camera's state while the
  camera does not record and its recorder runs, but on a lens the phone leaves out -- how long ago
  it came, past a minute: a failure said once goes on.
- **FR-006**: The log costs the video nothing: a recorder that cannot write it, or a message it
  cannot read, records on.
- **FR-007**: Covered by automated tests: the log kept, cut and limited, the messages written and
  read, sent again until answered (JVM); the messages read, the file, the answers, the heartbeat
  (pytest); the camera's line (Qt test).

## Success Criteria *(mandatory)*

- **SC-001**: On the emulator, the app's start and the camera it opened are in `phone.log` within
  2 s of starting.
- **SC-002**: With the recorder stopped for 20 s while the app runs, the lines of those 20 s reach
  `phone.log` within 10 s of the recorder starting again, none twice: a recorder silent for 10 s
  is sent to every 5 s (FR-002), then the lines it missed at full pace.
- **SC-003**: Nothing of the recording changes: the same frames recorded with the log as without.

## Assumptions

- Android lets an app read only its own process's part of the system log: the camera service's
  own lines (a camera driver failing) still need a cable; what the service answers the app --
  error codes, exceptions -- and what the framework says in the app's process is enough to tell
  which lens, size or rate failed.
- The log is the maintainer's and the referee's, on the venue's own network as the video is.
