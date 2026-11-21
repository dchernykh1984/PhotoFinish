# Feature Specification: Playing faster, slower and backwards

**Feature Branch**: `feat/sound-and-speed`

**Created**: 2026-11-21

**Status**: Draft

**Input**: Maintainer, 2026-11-21: the desktop program plays the video at its own speed only. It
should play faster and slower: x0.5 and x2 at first; x2 pressed, x1 and x4 are offered, and so
on, doubling; x0.5 pressed, x0.25 and x1. A button x1 is always there to go back to the own
speed. And it should play backwards: Play > and Play <, not Play alone.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Slow motion over the finish (Priority: P1)

Two riders cross together. The referee plays the seconds before the line at x0.25 to see who
leads, pauses on the frame, and times it as before.

**Why this priority**: a close finish is judged by watching it slowly; stepping frame by frame
loses the motion.

**Independent Test**: At x0.25 a recording of 1 s plays in 4 s, every camera following.

**Acceptance Scenarios**:

1. **Given** the video at its own speed, **When** the referee presses x0.5, **Then** it plays at
   half speed and the buttons offer x0.25 and x1.
2. **Given** x4, **When** the referee presses x1, **Then** it plays at its own speed again.
3. **Given** a speed other than x1, **When** the referee pauses, **Then** the frame shown is
   held and timed as at any speed.

### User Story 2 - Back over a crossing (Priority: P1)

The referee passed a crossing while playing; "Play <" plays the video backwards from the frame
shown, at the speed chosen, until Pause, or the recording's first frame.

**Why this priority**: going back over a moment is as common as going forward to it.

**Independent Test**: Backwards at x1 from a frame 2 s into a recording, the first frame is
reached 2 s later and the video holds there.

**Acceptance Scenarios**:

1. **Given** the video held, **When** "Play <" is pressed, **Then** it plays backwards and the
   button reads "Pause"; pressed again, the frame shown is held.
2. **Given** playing backwards, **When** "Play >" is pressed, **Then** it plays forwards from the
   frame shown.
3. **Given** playing backwards, **When** Stop is pressed, **Then** the video goes back to the
   frame playing started from, as forwards.

### Edge Cases

- Forwards past the newest frame of a camera that records is Live, as now; a file opened as it
  is ends there. Backwards past the first frame holds the first frame.
- A gap in the recording longer than a second is jumped over in either direction.
- A computer that cannot decode fast enough shows fewer frames, never late ones, at every speed.
- The speed is kept from one Play to the next, through Pause and Stop, until changed; a speed
  changed while playing takes effect from the frame shown.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Beside Stop, three buttons: half the speed, x1, and twice the speed, the first and
  the last naming the speed they set; the speed in use is said beside them. Speeds go from x1/16
  to x16, doubling and halving; a button past them is disabled; x1 is disabled at x1.
- **FR-002**: "Play >" plays forwards and "Play <" backwards, at the speed chosen, every camera
  following; the button of the direction playing reads "Pause".
- **FR-003**: Playing backwards ends at the first frame, held; forwards ends as it does today.
- **FR-004**: Timing waits for Pause at every speed and in both directions, as it does today.
- **FR-005**: Stepping back a frame, or playing backwards, takes the frames decoded lately from
  where they are kept, never decoding from the keyframe once a frame: a stretch between two
  keyframes is decoded once where the keep holds it -- 1080p at 30 fps and below -- and a few times
  at 1440p 60 fps, whose second of frames is larger than the keep.

## Success Criteria *(mandatory)*

- **SC-001**: At x0.25, x0.5, x2 and x4, a recording plays in 4, 2, 1/2 and 1/4 of its length.
- **SC-002**: Backwards from 2 s in, the first frame is shown 2 s later at x1.
- **SC-003**: A 1440p 60 fps recording plays backwards at x1 with no fewer frames a second than
  half of those it plays forwards on the same computer.

## Assumptions

- The limits x1/16 and x16 are the maintainer's "and so on" made finite: slower shows one frame
  for seconds, faster skips most frames.
- Sound (`specs/013-sound`) follows the speed forwards and is silent backwards.
