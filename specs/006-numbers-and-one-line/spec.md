# Feature Specification: Riders' numbers, every camera's crossings together, one finish line

**Feature Branch**: `docs/release-pr-pipeline` (PR #20, at the maintainer's word)

**Created**: 2026-11-11

**Status**: Draft -- experimental, off by default, as 002

**Input**: Issue [#21](https://github.com/dchernykh1984/PhotoFinish/issues/21), "neural networks go
through the video of every camera and build the protocol: one finds what moves, another the riders,
a third -- maybe the second -- the moment they cross the finish line"; and the maintainer, 2026-11-11:

- Finding motion is switched on and off on its own; with it on, reading the riders' numbers and
  the moments they cross the finish line is switched on and off too.
- The networks look at every camera, so the moment a wheel crosses is known more exactly.
- One finish line for all cameras, which the referee moves; a camera whose line was set on its own
  keeps it when the common one moves.
- The line is always shown and not edited by accident: a checkbox, or an edit mode, first.
- A crossing is when any part of the moving rider reaches the line.

What 002 already gives: finding riders by motion or by a detection model, the stretches and "Next
rider", suggestions when the front of a detected rider -- the first part of it to reach the line --
crosses a camera's line, each camera's line drawn with two clicks after "Finish line". This
specification adds the rest.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A suggestion with the rider's number, seen by every camera (Priority: P1)

With finding riders and "Numbers and crossings" on, a rider crossing the line gives one suggestion,
however many cameras saw it: at the middle of the moments they give, with the number read from
the rider. The referee checks it and accepts it -- with the number read, or one typed over it.

**Why this priority**: It is the protocol built for the referee to check, instead of from nothing.

**Independent Test**: Two cameras' suggestions 20 ms apart make one, at their middle, with the
number read; accepting it decides both. Two whose numbers were read apart stay two.

**Acceptance Scenarios**:

1. **Given** cameras whose suggestions for one crossing lie within 0.3 s of each other (offsets
   applied), **Then** the list shows one, at the median camera's moment, naming the cameras.
2. **Given** a number read from the rider at the crossing, **Then** the suggestion shows it, and
   "Accept" takes it when no number is typed; a number typed is taken over it.
3. **Given** a number that cannot be read, **Then** the suggestion has none and needs one typed.
4. **Given** "Numbers and crossings" off, **Then** finding riders works by motion alone, as 002
   without a model: no suggestions, no numbers.

### User Story 2 - One finish line, kept per camera where set on its own (Priority: P1)

The referee draws the finish line once for all cameras; a camera whose view needs its own is given
its own, which stays when the common one moves. The lines are always shown and only changed in the
finish-line edit mode.

**Acceptance Scenarios**:

1. **Given** edit mode on and "This camera only" off, **When** the referee clicks the line's two
   ends on a camera's picture, **Then** every camera that follows the common line takes it, that
   camera included.
2. **Given** "This camera only" on, **Then** the two clicks set that camera's own line, which the
   common line's moves leave alone.
3. **Given** edit mode off, **Then** clicks on a picture are the caliper's, never a line's ends.
4. **Given** a session from before, **Then** a camera whose line was drawn keeps it as its own;
   one on the centre line follows the common line.

### Edge Cases

- The number reader's models cannot be downloaded: suggestions come without numbers, and it is said.
- Two riders crossing within 0.3 s on several cameras: suggestions of one camera are never merged
  with each other, so each rider keeps one, nor are suggestions whose numbers were read apart; a
  merge across cameras of riders whose numbers were not read may pair them wrongly, and the
  referee sees each camera's moment in the suggestion to tell.
- A number half hidden by an arm: read as fewer digits, or not read; the referee types it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Two switches: "Find riders" (002's motion index) and, with it on, "Numbers and
  crossings": the detection model chosen, its suggestions, and the numbers read. Off, the
  analysers run on motion alone whatever model is chosen.
- **FR-002**: The numbers are read with two ONNX models, PaddleOCR's PP-OCRv3 English text detector
  and recogniser (Apache-2.0), downloaded from RapidOCR's mirror pinned by commit, size and
  SHA-256 -- about 11 MB -- when "Numbers and crossings" is on with a detector chosen, and kept next to the
  program. At a suggested crossing, the text in the rider's box is found and read; the longest run
  of digits of the most confident reading of at least 0.8 is the rider's number -- a year or a
  team's number on the line beside it is not run into it.
- **FR-003**: Suggestions of different cameras within 0.3 s of each other, offsets applied, are one
  crossing -- each joining the nearest, unless they read different numbers, or one of its cameras
  has a suggestion nearer to it: two riders -- listed once at the median camera's moment (for an even
  count, the earlier of the two in the middle) with each camera's, the number read, and
  accepted or dismissed together; the journal names that camera and its frames, which give the
  time written. A camera's suggestion arriving after its crossing was decided is offered still,
  with that decision said: it may be another rider.
- **FR-004**: The session keeps a common finish line; a camera follows it until a line is drawn
  for it alone ("own"). A camera whose line was drawn before this feature keeps it as its own.
- **FR-005**: The finish line is edited only in its edit mode -- a switch -- where two clicks on a
  picture set the common line, the camera clicked following it again, or, with "This camera only",
  that camera's own line. Out of the mode, clicks belong to the caliper.
- **FR-006**: A crossing is the moment the edge of the rider's box that leads across the line
  reaches it -- the first part of the rider, whatever it is (002, FR-007, unchanged).
- **FR-007**: Automated tests: the common and own lines, the edit mode, the switches, the merge of
  suggestions, the number reading on a fake model and on the pinned models by hand.

## Assumptions

- Training the networks on the event's own video is a later step of #21.
- A number on the rider's back, hip or bike, facing a camera; one turned away is read by none.
