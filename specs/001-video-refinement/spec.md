# Feature Specification: Refine crossing times from video

**Feature Branch**: `chore/bootstrap` (written with the repository's bootstrap)

**Created**: 2026-10-28

**Status**: Draft -- three questions open, marked NEEDS CLARIFICATION

**Input**: ChronometerPython issue
[#49](https://github.com/dchernykh1984/ChronometerPython/issues/49) and its comments.
Maintainer's decisions of 2026-10-28: video is a program of its own, in its own repository;
it takes the crossings of any timing source and writes its result to files of its own,
leaving the source untouched; the first versions are worked by hand, computer vision may
come later.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Correct a crossing time against one camera (Priority: P1)

The referee opens the results file a chronometer wrote -- by hand, by light beam or by
chips, on a laptop or a phone -- and a recording from the finish camera. For a crossing,
PhotoFinish shows the video at the recorded time; the referee steps frame by frame to the
frame where the rider crosses the line and accepts it. The crossing's time is replaced in
PhotoFinish's corrected copy; the chronometer's file stays as it was.

**Why this priority**: It is the whole value with a single camera, and every other story
builds on it.

**Independent Test**: Take a results file and a recording aligned with it; correct two
crossings. The source file is byte-for-byte the same, the corrected copy differs from it in
exactly those two times, and the journal holds two entries.

**Acceptance Scenarios**:

1. **Given** a results file with `15#20389 11:35:29.615#nextLap#` and a recording covering
   that moment, **When** the referee accepts the frame showing number 15 on the line at
   11:35:29.582, **Then** the corrected copy holds `15#20389 11:35:29.582#nextLap#` in the
   same place, every other line is identical to the source, and the source is unchanged.
2. **Given** a correction just accepted, **When** PhotoFinish is killed and started again,
   **Then** the correction is still there.
3. **Given** a corrected copy, **When** FinishProtocolGeneratorPython reads it instead of the
   source, **Then** it builds the protocol with the corrected times and needs no change.
4. **Given** a crossing whose time falls outside every opened recording, **Then**
   PhotoFinish says so instead of showing an unrelated moment.

---

### User Story 2 - Several cameras in step (Priority: P2)

The referee opens recordings from two or more cameras, for example the line from the side
and the numbers from the front. Moving through time moves all of them to the same moment,
so a rider hidden on one camera is read on another, and a correction can be made on any of
them.

**Why this priority**: In a bunch finish riders hide each other and one camera cannot read
every number; still, a single camera is already useful on its own.

**Independent Test**: Open two recordings of the same scene, align them, step to one
visible event (a flash): it shows on both at the same time, within one frame interval.

**Acceptance Scenarios**:

1. **Given** two recordings whose cameras started at different moments, **When** the
   referee marks one event visible to both -- a hand wave or an LED flash in front of all
   cameras -- on each, **Then** PhotoFinish derives the offset between them and from then
   on shows the same moment on both, within one frame interval.
2. **Given** aligned cameras, **When** the referee corrects a crossing on the second camera,
   **Then** the journal names that camera.

---

### User Story 3 - Align the video with the timing source (Priority: P3)

The chronometer's clock and the cameras' clocks differ: a laptop, a beam timer, a chip
reader and each camera have their own offset and delay. The referee aligns them once by an
event seen on both sides -- a chip carried past the antenna in view of the cameras, the beam
broken in view of the cameras -- and from then on every crossing opens at the right moment.

**Why this priority**: Without it the referee searches around each crossing by hand; with
it every jump lands on the rider. It pays off only once Story 1 works.

**Independent Test**: Mark one known event on the video and on the timing side; later
crossings of that source open within one frame of where the rider crosses, for a source
whose own error is below a frame.

**Acceptance Scenarios**:

1. **Given** a chip reading and the video frame of the same passing, **When** the referee
   marks the pair, **Then** PhotoFinish keeps the offset between that timing source and the
   video and opens every later crossing of the source shifted by it.
2. **Given** an offset in use, **Then** it is saved with the session and shown, so it can be
   checked after the race.

---

### Edge Cases

- The chronometer is still recording: lines appear in the source while PhotoFinish has it
  open. They appear in the corrected copy as they are, and earlier corrections stay applied.
- The referee changed a line in the chronometer after correcting it here (another number or
  time): the correction no longer matches its source line, and PhotoFinish reports it
  instead of applying it to the wrong crossing.
- The same number crosses several times (laps): each crossing is corrected on its own; a
  correction belongs to one line, not to a number.
- Two identical lines (the same crossing saved twice): a correction says which of them it
  changes.
- A source file from the older C++ tools in cp1251; a source whose last line is still being
  written.
- A recording made at a variable frame rate (phones): times come from each frame's own
  timestamp, not from its index.
- Daylight saving time: the chronometers keep local standard time, so in summer their clock
  can be an hour off the wall-clock time a camera stamps. The offsets of Story 3 absorb it;
  nothing assumes the two clocks agree.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: PhotoFinish MUST open the timing files it reads for reading only, and MUST
  NOT write, rename, truncate or lock them.
- **FR-002**: PhotoFinish MUST read crossing lines `number#time#action#`, the time as
  `D H:M:S[.mmm]` in local standard time (hours, minutes and seconds not zero-padded; milliseconds, when recorded,
  always three digits), from any
  chronometer of the set -- desktop or Android, by hand, by beam or
  by chips -- including files from the older C++ tools (UTF-8, then cp1251, then Latin-1).
- **FR-003**: PhotoFinish MUST write its result as a corrected copy: every line of the
  source in source order, the lines it does not correct byte for byte, and a corrected
  time written the way the chronometers write it, so FinishProtocolGeneratorPython reads
  the copy unchanged.
- **FR-004**: Every correction MUST be written to a journal next to the corrected copy when
  the referee accepts it, with the source line it corrects -- its number, recorded time and
  action, and which occurrence it is when the same line appears more than once -- the new
  time, the camera and the frame.
- **FR-005**: The corrected copy MUST be the source with the journal applied: lines the
  chronometer adds later appear in it, and a correction whose source line has changed is
  reported, not applied. A correction MUST identify its source line even when the same
  line occurs more than once.
- **FR-006**: The referee MUST be able to step through a recording frame by frame, see each
  frame's time to the millisecond, and accept the frame at which a rider crosses the line.
- **FR-007**: PhotoFinish MUST show several recordings in step and let the referee align
  the cameras by marking one shared event on each.
- **FR-008**: PhotoFinish MUST let the referee align a timing source with the video by
  marking one event on both, and MUST keep the offsets in use with the session.
- **FR-009**: PhotoFinish MUST run as a program of its own that exchanges only files with
  the chronometers; its failure MUST NOT affect them.
- **FR-010**: PhotoFinish MUST keep its files next to itself, so one copy of the folder
  serves one event.
- **FR-011**: Corrections are made by the referee. Finding the crossing frame
  automatically (computer vision) is outside this feature.
- **FR-012**: The recordings PhotoFinish works with MUST come from [NEEDS CLARIFICATION:
  which cameras first -- files copied from action cameras or phones after the race (high
  frame rate, no live view), USB cameras PhotoFinish records itself during the race (live,
  about 30 fps), or both?].
- **FR-013**: Corrected times MUST reach the results [NEEDS CLARIFICATION: only through
  FinishProtocolGeneratorPython reading the corrected copy for the final protocol, or also
  as live updates on the site, which needs a site change because the site keeps each
  device's stream exactly as it was sent?].
- **FR-014**: A correction MUST be able to change [NEEDS CLARIFICATION: the time only, or
  also the number -- a misread bib, a chip worn by the wrong rider -- and add a crossing the
  timing source missed?].

### Key Entities

- **Source file**: a chronometer's results file, one `number#time#action#` crossing per
  line; owned by the chronometer, read only here.
- **Recording**: one camera's video, with each frame's own timestamp.
- **Camera offset**: what turns a camera's frame time into the common video time; set by
  marking a shared event.
- **Source offset**: what turns a timing source's time into the video time; set by marking
  an event seen on both sides.
- **Correction**: one source line -- number, recorded time, action and, for a line that
  repeats, which occurrence -- its new time, the camera and the frame it was read from.
- **Corrected copy**: the source with the corrections applied, in the same format.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After any session, including one ended by killing the program, every source
  file is byte-for-byte what the chronometer wrote.
- **SC-002**: Killing PhotoFinish loses no correction the referee had accepted.
- **SC-003**: FinishProtocolGeneratorPython builds a protocol from the corrected copy with
  no change to the generator.
- **SC-004**: With cameras aligned by one shared event, the same moment shows on every
  recording within one frame interval.
- **SC-005**: Every corrected time can be traced through the journal to one camera and one
  frame.

## Assumptions

- Accuracy is bounded by the frame rate, about half a frame interval: +-17 ms at 30 fps,
  +-2 ms at 240 fps. The three decimals of the time format are resolution, not accuracy
  (constitution, principle V).
- The plan settles the file names and the journal's line format. Issue #49 sketched
  `results_video.txt` for the copy and `corrections.txt` with
  `number#old_time#new_time#camera#` lines; that sketch lacks the action and the frame
  FR-004 asks for and cannot tell identical lines apart, so the plan extends it.
- The chronometers, FinishProtocolGeneratorPython and the site need no change for this
  feature, unless FR-013 asks for live updates.
- The plan picks the video library; heavy dependencies arrive with this feature.
- If FR-012 includes recording live, recording runs in a process separate from the editor,
  so an editor crash loses no frames (issue #49; CrossMgr moved its camera into a separate
  process after losing frames).
