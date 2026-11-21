# Feature Specification: The start protocol's numbers for the number reader

**Feature Branch**: `feat/sound-and-speed`

**Created**: 2026-11-21

**Status**: Draft

**Input**: Maintainer, 2026-11-21: a path to the start protocol file can be given; its format is
StartProtocolMaker's. Its start numbers help the reader find the riders' numbers, not the
writing and stickers around them. How SportPhotoIndexer reads bibs on photos may help, knowing
which numbers the race has.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Numbers read are riders' numbers (Priority: P1)

The referee chooses the race's `start.txt`; from then on a number read at a suggested crossing
is one of the race's: a rider's jersey that says "2026" or a sponsor's phone number is passed
over for the bib under it, and a number nobody starts with is never suggested.

**Why this priority**: a wrong number accepted is a wrong result; a suggestion without a number
costs only a keystroke.

**Independent Test**: A box whose surest text is "2026" and whose next is "37", read with a
protocol holding 37: the number is 37; without the protocol: 2026.

**Acceptance Scenarios**:

1. **Given** a protocol holding 7, **When** "007" is read, **Then** the number is 7, as the
   protocol spells it.
2. **Given** a protocol, **When** only numbers not in it are read, **Then** the crossing comes
   without a number.
3. **Given** no protocol, **Then** numbers are read as today.

### Edge Cases

- The protocol edited during the race -- a late entry -- is read again when it changes.
- A file that cannot be read, or holds no number: said beside the button; the reader goes on as
  without one.
- A relay's line of N stages and a numeric number holds number to number + N - 1, as
  FinishProtocolGenerator counts them.
- A line whose first field holds no digit -- a header, an unpaid marker -- holds no number.
- Numbers with letters ("A12") stay in the protocol; the reader reads digits only, so it never
  suggests them: they are typed, as today.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: "Start protocol..." beside the number reader's switches chooses the file; the
  session keeps its path; the button names the file and how many numbers it holds. The file is
  only read.
- **FR-002**: A start number is the first field of a line, split at `#`, `;`, `,` or a tab, with
  a digit in it; a line whose fifth field says N > 1 stages adds the N - 1 numbers after a
  numeric one. UTF-8, cp1251 and Latin-1 are tried in that order.
- **FR-003**: With a protocol, the reader's number is the surest reading -- of at least the
  usual 0.8 -- whose digits, leading zeros aside, are a start number, spelled as the protocol
  spells it; without one, as today.
- **FR-004**: The analysers read the protocol again when its path or the file changes, from the
  next segment they read on.

## Success Criteria *(mandatory)*

- **SC-001**: With a protocol, no suggested number is outside it.
- **SC-002**: A box with a sticker read surer than the bib still gives the bib's number.

## Assumptions

- SportPhotoIndexer's measurements: a protocol removes the values that match no starter, while
  a starter's number on a sticker stays; keeping weaker reads of starters' numbers found few
  more and many wrong, so the threshold is not lowered for them.
