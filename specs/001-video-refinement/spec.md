# Feature Specification: Live finish video and the referee's list of crossings

**Feature Branch**: `feat/live-video-editor`

**Created**: 2026-10-28 (bootstrap draft); rewritten 2026-10-29

**Status**: Draft

**Input**: ChronometerPython issue [#49](https://github.com/dchernykh1984/ChronometerPython/issues/49),
comments 1-8. The maintainer's decisions of 2026-10-28 replace the bootstrap draft's model (a
corrected copy of one results file and a recording opened after the race) and answer its three
open questions:

- The cameras stream to the computer; PhotoFinish records them, and the referee scrolls the video
  back and forth while it is still being recorded. The main work is timing by hand from the video
  as it grows.
- No live video on the site; the result is a file.
- The referee can change a crossing's time and number, add a crossing and remove a false one.
- Two lists. The input list shows one file, read only; several chronometers may feed that file.
  The output list is the referee's, editable, saved to another file. New input lines arrive in
  the output by themselves; a change to an input line already taken does not.
- Both lists follow the video: with the video at 12:35:28, the crossings nearest that time are in
  view.
- A time between two frames may be set the way a caliper reads between its marks, or picked on a
  zoomed timeline (constitution, principle V).
- Cameras: SJCAM HD1080P and SJCAM SJ10 Pro. Build what their specifications allow; the
  maintainer and the developer debug them together later.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record the finish camera and scroll it while it records (Priority: P1)

The referee picks a camera and starts recording. The picture appears at once and the timeline
grows at its end. The referee drags the timeline back to any moment, steps frame by frame, and
returns to the newest frame with "Live", while recording goes on. Every frame shows its time to
the millisecond.

**Why this priority**: Everything else is done on this video; without it there is nothing to time
or check.

**Independent Test**: Record the test camera, which draws its own clock into each frame, for a
minute; meanwhile seek to second 10 and step a few frames: the drawn clock and the shown time
agree within one frame, and the recording has no gap.

**Acceptance Scenarios**:

1. **Given** a camera that sends a keyframe at least every 2 s, **When** the referee starts
   recording, **Then** the newest frame can be viewed within 2 s of its capture and the timeline
   grows; a camera with keyframes farther apart shows its newest frames that much later.
2. **Given** recording, **When** the referee scrolls back 5 minutes, **Then** the frame of that
   moment is shown and recording continues without a gap.
3. **Given** recording, **When** the window is killed, **Then** recording continues; started
   again, the window shows everything recorded, including the time it was closed.
4. **Given** a camera that drops out, **Then** the recorder reconnects with a growing pause, the
   gap is shown on the timeline, and nothing recorded before is lost.
5. **Given** less than 2 GB free on the disk, **Then** the referee is warned; when the disk is
   full, recording stops cleanly, says so and keeps what it recorded.

---

### User Story 2 - Time crossings by hand from the video (Priority: P1)

The referee steps to the frame where a rider crosses the line, types the number and presses Enter:
the crossing is added to the output list and saved at that frame's time. Stepping one frame, ten
frames and one second each way and adding a crossing all work from the keyboard, because at a
bunch finish the referee adds dozens of crossings in a few minutes.

**Why this priority**: It is the main function the maintainer asked for: timing from the video
while it is still being recorded.

**Independent Test**: With the test camera, add a crossing for 15 at a chosen frame: the output
file gets `15#<that frame's time>#nextLap#` and the journal names the camera and the frame.

**Acceptance Scenarios**:

1. **Given** a frame at 11:35:29.582, **When** the referee types 15 and presses Enter, **Then** the
   output file gets `15#<day> 11:35:29.582#nextLap#`, or `finish` with finish mode on, and the
   journal records the camera and the frame.
2. **Given** recording goes on, **Then** adding a crossing never waits for the recording and never
   disturbs it.
3. **Given** the program is killed right after the referee added a crossing, **Then** the crossing
   is in the output file when it starts again.

---

### User Story 3 - The chronometer's crossings in, the referee's crossings out (Priority: P1)

The referee chooses the input file -- a chronometer's results file, or one file several sources
feed -- and the output file. The input list shows the input lines read only; the output list
starts from them. New input lines arrive in the output by themselves. A change to an input line
already taken -- a judge corrected it at the chronometer -- does not: the input list highlights it
with the old and the new content, and the referee copies it over if they agree. A line that
disappears from the input stays in the output, marked. Both lists follow the video: the lines
nearest to the video's time are brought into view and marked; selecting a line moves the video to
its time.

**Why this priority**: The chronometer's crossings are where the referee starts; the output is
what the protocol is built from.

**Independent Test**: Input with three lines: the output gets three. The chronometer appends one:
the output gets four. The chronometer changes the second line's time: the output keeps the old
time and the input list highlights the change; "Copy to output" takes it, journaled.

**Acceptance Scenarios**:

1. **Given** an input file being appended to, **Then** each new line appears in the output within
   2 s, with its bytes unchanged.
2. **Given** an input line already taken changes, **Then** the output keeps the line it took, the
   input list highlights the change with both contents, and "Copy to output" replaces the output
   line, journaled.
3. **Given** an input line disappears, **Then** its output line stays, marked "removed from
   input".
4. **Given** the video at 12:35:28, **Then** both lists show the lines nearest that time and mark
   them.
5. **Given** the referee selects a line in either list, **Then** the video moves to its time.
6. **Given** PhotoFinish starts again, **Then** it knows which input lines it took: lines added
   while it was closed arrive as new, changes made while it was closed are highlighted.
7. **Given** the referee removed an output line taken from the input, **Then** that input line
   does not bring it back.

---

### User Story 4 - Correct the output: time, number, add, remove (Priority: P1)

The referee sets a crossing's time from the current frame, types a time, changes its number, adds
a crossing the chronometer missed (Story 2) or removes a false one after a confirmation. Every
change is saved at once and journaled.

**Why this priority**: Correcting the chronometer is what the video is for at the finish of a
race timed by beam or chips.

**Independent Test**: Change a time from a frame, change a number, add one crossing and remove one:
the output file shows exactly those four changes, the journal has four entries, and the input file
is byte for byte as the chronometer wrote it.

**Acceptance Scenarios**:

1. **Given** an output line, **When** the referee sets its time from the current frame, **Then** the
   line's time changes and the journal records the old and the new time, the camera and the frame.
2. **Given** a mistyped number, **When** the referee changes it, **Then** the line changes in place.
3. **Given** a false crossing, **When** the referee removes it and confirms, **Then** it is gone
   from the output and the journal keeps it; the input is untouched.
4. **Given** a typed time that is not a valid `D H:M:S[.mmm]`, **Then** the change is refused.
5. **Given** the output file, **When** FinishProtocolGeneratorPython reads it as a finish file,
   **Then** it builds the protocol with no change to the generator.

---

### User Story 5 - A time between two frames, read like a caliper (Priority: P2)

On the frame before the crossing and on the frame after it the referee clicks the same point of
the rider -- the leading edge of the front wheel. With the finish line drawn on that camera's view,
PhotoFinish interpolates the moment the point crossed it, assuming a steady speed over one frame.
Alternatively the referee zooms the timeline until one frame interval is wide and clicks between
the two frames. The referee can adjust the result by hand before accepting it.

**Why this priority**: It turns a 60 fps camera's +-8 ms into a few milliseconds, which separates
riders in a sprint; it needs Stories 2 and 4 first.

**Independent Test**: The test camera at 60 fps moves a bar at constant speed; on frame k its edge
is 3 units before the line and on frame k+1 1 unit past it: the time offered is that of frame k
plus three quarters of the frame interval, within 1 ms, and the journal says "interpolated between
frames k and k+1, 0.75".

**Acceptance Scenarios**:

1. **Given** the finish line drawn and a point clicked on two frames on either side of it,
   **Then** the interpolated time is shown, and accepting it sets the crossing's time.
2. **Given** the timeline zoomed so that one frame interval is at least 100 pixels wide, **When**
   the referee clicks between two frames, **Then** that time is offered, recorded as picked by
   hand between those frames.
3. **Given** two points on the same side of the line, **Then** nothing is offered and the referee
   is told why: PhotoFinish interpolates, it does not extrapolate.
4. **Given** an interpolated or hand-picked time, **Then** the output list marks it as such.

---

### User Story 6 - Several cameras in step (Priority: P2)

The referee records two or more cameras, for example the line from the side and the numbers from
the front. Moving through time moves all of them to the same moment, so a rider hidden on one
camera is read on another, and a crossing can be timed on any of them.

**Why this priority**: In a bunch finish riders hide each other and one camera cannot read every
number; still, one camera is useful on its own.

**Independent Test**: Record two test cameras showing the same flash, align them on it, and step
to the flash: it shows on both within one frame interval.

**Acceptance Scenarios**:

1. **Given** two cameras whose clocks or delays differ, **When** the referee marks one event both
   show -- a hand wave or a flash in front of all cameras -- on each, **Then** PhotoFinish keeps the
   offset between them and from then on shows the same moment on both, within one frame interval.
2. **Given** aligned cameras, **When** the referee times a crossing on the second camera, **Then**
   the journal names that camera.
3. **Given** cameras at different frame rates, **Then** each shows its frame nearest the moment.

---

### User Story 7 - Align the video with the timing source (Priority: P3)

The chronometer's clock and the video's differ: a phone, a chip reader and each camera have their
own offset, and a network camera shows its picture seconds late. The referee aligns them once on an
event seen on both sides -- a chip carried past the antenna in view of the camera, the beam broken
in view of the camera -- and from then on input lines open at the right moment and the times the
referee sets are written on the chronometer's clock.

**Why this priority**: Without it the referee searches around each crossing by hand; with it every
jump lands on the rider. It pays off once Stories 1-4 work.

**Independent Test**: Mark one input line and its frame; later input lines open within one frame of
the rider for a source whose own error is below a frame, and a crossing added from a frame carries
the chronometer's time of that frame.

**Acceptance Scenarios**:

1. **Given** an input line and the frame of the same passing, **When** the referee marks the pair,
   **Then** PhotoFinish keeps the offset and applies it both ways: input lines open shifted by it,
   times set from frames are written shifted back.
2. **Given** an offset in use, **Then** it is shown and saved with the session, and the journal
   records it with every time set from a frame.

---

### User Story 8 - The cameras the maintainer owns, and test cameras (Priority: P2)

The camera list offers connections and presets. Connections: a USB camera, a network stream
PhotoFinish fetches (RTSP), a stream PhotoFinish receives (RTMP), a test camera and a video file
played as if it were live. Presets for the maintainer's cameras fill a connection in: SJCAM HD1080P
over USB (it shows up as a "PC Camera", 720p at 30 fps), SJCAM HD1080P over its own Wi-Fi
(`rtsp://192.168.1.254/sjcam.mov` once the computer joins the camera's access point) and SJCAM SJ10
Pro (the SJCAM app pushes the stream to `rtmp://<this computer>/live/<name>`; PhotoFinish shows the
address to type in the app). A recording made by a camera on its own card can also be opened after
the race and placed on the timeline by alignment.

**Why this priority**: The maintainer's cameras are what will be used at races; the test camera and
the file make every other story testable without them.

**Independent Test**: The test camera and a file played as live record on every release platform;
an RTMP stream pushed from the same computer is received and recorded.

**Acceptance Scenarios**:

1. **Given** a preset never tried with its real camera, **Then** it is labelled "untested".
2. **Given** an RTMP push to the address shown, **Then** it is recorded like any camera.
3. **Given** a camera with a variable frame rate, **Then** frame times come from each frame's own
   timestamp, not from its index.
4. **Given** a file opened after the race, **Then** it is shown on the timeline next to the live
   recordings once aligned, and is never changed.

### Edge Cases

- The input file's last line is still being written: it is taken once its line break is there.
- An input line without a time PhotoFinish can read (`15##`, a slot saved without a time): taken
  with its bytes, kept at the end of the output in input order and marked, so nothing the
  chronometer wrote is dropped.
- An input file from the older C++ tools in cp1251.
- The same number crosses several times (laps): each line is its own crossing; an edit belongs to
  one line, not to a number. Two identical lines are two crossings.
- The input file is emptied or replaced (a new competition at the chronometer): its old lines count
  as removed and are marked in the output; new lines arrive as usual.
- The computer's clock is changed during recording: frame times follow a steady clock from the
  start of the recording, so the change does not move frames already recorded.
- Daylight saving: the chronometers keep local standard time unless the desktop summer-time option
  is on; PhotoFinish writes times the same way, with the same option, and the offset of Story 7
  absorbs any remaining difference.
- A network camera's picture arrives seconds late (about 4-5 s over the SJCAM Wi-Fi): until the
  camera is aligned (Story 7), its frames show earlier riders than their arrival times suggest.
- A recording of many hours: the timeline zooms from the whole recording down to single frames.
- An RTMP camera that never connects -- the computer's firewall blocks the port, or the phone
  running the camera app is on another network: the camera's state says it is still waiting and
  shows the address and port the camera app must reach.
- The output file is changed by something else while PhotoFinish runs: PhotoFinish notices, keeps
  the outside version in a backup, and writes its own list; the journal records it.
- The referee chooses an output file that already has crossings PhotoFinish did not write: they
  become the start of the output list, journaled as outside content, and an input line whose exact
  text is already among them counts as taken.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The input file is opened for reading only; PhotoFinish never writes, renames,
  truncates or locks it, and reads it again whenever it grows or changes. It keeps the file open only
  while it reads it, so a chronometer replacing the file (an edit on the desktop) is not refused on
  Windows because PhotoFinish holds it.
- **FR-002**: Crossing lines `number#time#action#` are read from any chronometer of the set,
  including files from the older C++ tools (UTF-8, then cp1251, then Latin-1). The time is
  `D H:M:S[.mmm]` in local standard time, one hour later with the desktop chronometer's
  summer-time option during daylight saving; hours, minutes and seconds are not zero-padded and
  milliseconds, when recorded, are always three digits.
- **FR-003**: Each camera is recorded to disk in pieces, each readable once closed, by a process
  separate from the window, in a folder per camera inside the event folder. Each frame's time on the
  computer's clock -- a steady clock anchored to the wall clock when recording starts -- is kept with
  the video.
- **FR-004**: Any recorded frame can be shown while recording goes on; the newest frame can be
  viewed within 2 s of its capture, or within the camera's keyframe interval when that is longer
  (a network stream is stored as the camera encoded it); "Live" follows the newest frame.
- **FR-005**: A camera that drops out or a recorder that fails is started again after 1 s, the pause
  doubling to at most 30 s while it keeps failing and back to 1 s after 30 s without a failure; the
  gap is shown on the timeline; nothing recorded before is lost.
- **FR-006**: Below 2 GB of free disk the referee is warned; on a full disk recording stops cleanly
  and says so.
- **FR-007**: Camera connections: USB camera, RTSP stream, RTMP receiver, test camera, file played
  as live. Presets: SJCAM HD1080P (USB), SJCAM HD1080P (Wi-Fi, RTSP), SJCAM SJ10 Pro (RTMP). A
  preset not yet tried with its camera is labelled "untested". A recorded file can be opened as a
  camera that does not record.
- **FR-008**: The referee chooses the input file and the output file. The output file holds
  `number#time#action#` lines in time order; a line taken from the input keeps its bytes until the
  referee changes it.
- **FR-009**: PhotoFinish compares the input as it is with the input as it last took it: lines that
  were added are added to the output, in its time order; lines that changed are highlighted in the
  input list with both contents and are not applied; lines that disappeared stay in the output,
  marked. "Copy to output" applies a highlighted input line by hand.
- **FR-010**: The output can be changed by adding a crossing (a number, and a time from the current
  frame, interpolated or typed; the action from the finish-mode switch), changing a line's number
  or time, and removing a line after a confirmation. A typed time that is not a valid
  `D H:M:S[.mmm]` is refused. A removed or changed line is never brought back by the input.
- **FR-011**: Every change is written to the output file in one step, so a crash leaves the old or
  the new file, never a mix, and appended to a journal next to it: what was done, the line before
  and after, the input line it came from, the camera, the frames, how the time was obtained
  (frame, interpolated with its fraction, picked by hand, typed) and the offsets in use.
- **FR-012**: Both lists follow the video: the lines nearest the video's time are in view and
  marked. Selecting a line moves the video to its time, through the offsets.
- **FR-013**: Each camera has a finish line the referee draws on its view, the vertical centre line
  by default. A point clicked on two frames on either side of the line gives the crossing time by
  linear interpolation; points on one side give nothing. On a timeline zoomed so a frame interval
  is at least 100 pixels wide, a click between two frames gives that time. Such times are marked in
  the output list and recorded as such in the journal.
- **FR-014**: Several cameras are shown at the same moment, each at its frame nearest to it. A
  shared event marked on each camera sets the offsets between them.
- **FR-015**: An input line and the frame of the same passing set the offset between the timing
  source and the video; it applies both ways and is shown.
- **FR-016**: Stepping one frame, ten frames and one second each way, "Live", and adding a crossing
  for the typed number work from the keyboard.
- **FR-017**: The session -- input and output files, cameras and their settings, finish lines,
  offsets and the input as last taken -- is saved next to the program, and a restart resumes it.
- **FR-018**: PhotoFinish talks to no site and needs no internet; it talks to cameras over USB or
  the local network only.

### Key Entities

- **Camera**: a connection or preset, its finish line, its offset and its state.
- **Recording**: one camera's video on disk, in pieces, with each frame's time.
- **Input file / input list**: one file of crossings a chronometer, or several, write; read only.
- **Output file / output list**: the referee's crossings, same format.
- **Journal**: one entry per change of the output, with its origin.
- **Offsets**: between cameras, and between the timing source and the video.
- **Session**: everything needed to resume after a restart.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After any session, including one ended by killing the program, the input file is
  byte for byte what the chronometer wrote.
- **SC-002**: Killing the window while the test camera records loses no frame and no change of the
  output, proven by tests.
- **SC-003**: FinishProtocolGeneratorPython builds a protocol from the output file with no change,
  proven by a test that reads it with the generator's rules.
- **SC-004**: On the test camera's constant-speed bar, interpolation gives the true crossing time
  within 1 ms at 60 fps.
- **SC-005**: Cameras aligned on one shared event show the same moment within one frame interval.
- **SC-006**: With the test camera, the newest frame is viewable within 2 s of capture and a seek
  anywhere in a one-hour recording shows its frame within 0.5 s on the maintainer's laptop.
- **SC-007**: Every line of the output file can be traced through the journal to the input line it
  came from or to the camera and frames it was timed on.

## Assumptions

- Video is captured, recorded and decoded with FFmpeg through PyAV, which has wheels for every
  release platform; the plan picks the container and the piece length.
- SJCAM SJ10 Pro: no confirmed USB webcam mode; it streams over RTMP from the SJCAM app. SJCAM
  HD1080P (SJ4000 class): USB "PC Camera" at 720p30, and on the Wi-Fi model an RTSP stream through
  the camera's access point with a delay of 4-5 s. Both are to be checked with the real cameras.
- The output file is not uploaded anywhere in this feature; FinishProtocolGeneratorPython reads it
  as a finish file.
- Reading bib numbers and finding riders in the video are specification 002.
