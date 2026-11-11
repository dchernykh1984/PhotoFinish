# Feature Specification: Several lenses of one phone, and one camera large

**Feature Branch**: `docs/release-pr-pipeline` (PR #20, at the maintainer's word)

**Created**: 2026-11-11

**Status**: Draft

**Input**: Maintainer's decisions of 2026-11-11:

- "A finish decided by millimetres: switch to the telephoto and look at the line enlarged; something
  wider needed: switch to the ultra-wide." The phone records several of its lenses at once, the
  lenses chosen with checkboxes on the laptop, and the referee switches between them in the viewer.
- One camera large, with switching, besides all of them side by side.
- The front camera too, as one of the lenses: "it is no worse, and sometimes the other side of the
  phone is worth a look".
- Priority as for the app: the Xiaomi 17 Ultra, then the Xiaomi Mi 11 Ultra.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The referee ticks lenses on the laptop and the phone streams each (Priority: P1)

In the add-camera dialog for a phone, the referee ticks the lenses to record: Main, Ultra-wide,
Telephoto, Front. PhotoFinish adds a camera for each, on a port of its own, and shows one QR code
holding them all. PhotoFinish Camera scans it and streams every lens it has, each with its frames'
moments; a lens the phone lacks, or cannot stream with the others, is said on the phone, and its
camera keeps waiting.

**Why this priority**: The telephoto decides a finish of millimetres, the ultra-wide shows what
happened around it; both must be recorded while it happens -- a lens chosen afterwards has
nothing to show.

**Independent Test**: On the emulator, whose front camera is a logical camera of two lenses, two
lenses of one camera and the camera on the other side stream at once, each recorded by its own
recorder, each frame with its moment.

**Acceptance Scenarios**:

1. **Given** Main alone ticked (the default), **Then** the dialog shows one address and a QR code
   holding exactly it, as before: any streaming app can scan it.
2. **Given** Main and Telephoto ticked, **Then** two cameras are added, named after the lens when
   there are several, on two free ports, and the QR code holds both, one line per lens.
3. **Given** the code scanned and Start tapped, **Then** each lens streams to its own camera with
   its own clock exchange, and the camera list says recording for each.
4. **Given** a lens the phone lacks, **Then** the phone says so for that lens and streams the
   others.
5. **Given** lenses the phone cannot stream together, **Then** it streams the ones it can, in the
   order of the code, and says which it left out -- on its screen, and to the laptop in its status
   (`specs/005-phone-status`), whose phone line names them.

---

### User Story 2 - One camera large, and switching between cameras (Priority: P1)

The referee shows one camera over the whole video area and switches between the cameras with keys
or the camera list, or goes back to all of them side by side.

**Why this priority**: A telephoto's picture side by side with three others is a quarter of the
screen; the millimetres need it whole.

**Independent Test**: With two cameras recording, One camera shows the chosen one alone; the keys
switch to the other at the same moment and back to both.

**Acceptance Scenarios**:

1. **Given** several cameras, **When** the referee presses One camera or Ctrl+N, **Then** the
   chosen camera, or camera N of the list, fills the video area and the others are hidden; Ctrl+0
   shows them all side by side again.
2. **When** the referee presses Ctrl+Down or Ctrl+Up, **Then** the next or the previous camera of
   the list is chosen -- shown large in one-camera mode -- at the moment shown.
3. **Given** one-camera mode, **Then** the hidden cameras are not decoded; shown again, each
   shows its frame at the moment.
4. The keys work while a number is typed (001, FR-016).

### Edge Cases

- A lens that does not give the size or the rate chosen -- often the front camera, or several
  lenses at once -- streams at the nearest it gives, and the phone says what it streams.
- The Wi-Fi carries every lens: about 10 Mbit/s each at 1080p and 60 fps, 16 at 1440p.
- Several sensors and encoders heat the phone over hours: in the sun it may lower its frame rate.
- A code of the earlier kind, an address alone, still pairs: the main lens.
- A streaming app other than PhotoFinish Camera cannot read a code of several lines: lenses are
  PhotoFinish Camera's; with Main alone the code stays an address any app reads.
- A phone that shows apps only some of its lenses (Xiaomi has hidden its others): the app streams
  what it is given and says what it found.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The add-camera dialog's phone connection offers the lenses Main (ticked by default),
  Ultra-wide, Telephoto and Front. Each ticked lens is a camera of its own: the name typed,
  followed by the lens when more than one is ticked; the next free id; the port typed for the
  first lens and the next free ports for the others; the path typed for the first and
  `live/<id>` for the others. The session's format does not change: to PhotoFinish each is a
  phone's camera like any other.
- **FR-002**: The QR code holds the address alone for Main alone, else one line per lens,
  `<lens> <address>`, the lens one of `main`, `ultrawide`, `telephoto`, `front`
  ([contract](../003-phone-camera-app/contracts/phone-stream.md)). The text shown says the same:
  a lens other than Main keeps its line, as PhotoFinish Camera takes an address alone for Main's.
- **FR-003**: PhotoFinish Camera reads both forms, scanned or typed; a line it cannot read is
  said.
- **FR-004**: The app finds its lenses: the back camera's physical cameras when it is a logical
  camera of several, by 35 mm-equivalent focal length -- the one nearest the back camera's own
  is main, the shortest at four fifths of it or less ultra-wide, the longest at one and a half
  times or more telephoto -- and the front camera as a whole. It lists them, with their focal
  lengths, on its screen.
- **FR-005**: The app streams each lens asked for that it has: its own encoder, connection and
  clock exchange; the lenses of one camera in one capture session; the camera on the other side
  opened beside it only when the phone says it can run both at once, and closed alone when it is
  lost, the first streaming on. Each camera streams at the
  size and rate chosen, or the nearest its lenses give.
- **FR-006**: The preview shows the first lens streamed.
- **FR-007**: The window's One camera mode shows the chosen camera alone, over the whole video
  area; Ctrl+1 to Ctrl+9 show camera 1 to 9 alone, Ctrl+0 all of them side by side, Ctrl+Up and
  Ctrl+Down the previous and the next camera; the keys work while a number is typed. A hidden
  camera is not decoded.
- **FR-008**: Every part is covered by automated tests: the dialog's cameras and code, the
  window's mode and keys (Qt tests), the app's pairing, lens classification and session plan (JVM
  unit tests, Kover).

### Key Entities

- **Lens**: one of main, ultra-wide, telephoto, front; on the phone, a camera device and,
  for a logical camera, one of its physical cameras.
- **Lens target**: a lens and the address its stream goes to.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Two lenses stream at once on the emulator, each frame of each with its moment, each
  recorded by its own recorder.
- **SC-002**: On the Xiaomi 17 Ultra, the screen lists the lenses the phone gives the app, and
  the ones it can stream together do (checked by hand).
- **SC-003**: Switching cameras in the window keeps the moment shown, to the frame.

## Assumptions

- Physical cameras of a logical one are streamed from Android 10, which tells each one's focal
  length and sizes -- Android 9 streams them but throws when asked of a hidden one -- and says
  beforehand whether a set of streams is supported, and the app asks. On Android 9 the back
  camera's own picture is the main lens, the other lenses not on this phone.
- Two cameras open at once only where Android 11 or later lists the pair as concurrent; elsewhere
  the second is left out and said.
- The lenses' clocks are the phone's: every lens is in step with the others without Mark event.
