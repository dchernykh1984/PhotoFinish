# Tasks: A network break costs no frame

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## The recorder and the window

- [x] T001 [US1] `app/recorder/sources.py`: `held_ms` from the stream's metadata; a phone's moment
  believed up to it older (FR-006)
- [x] T002 [US1] `app/recorder/segments.py`: a frame whose moment was listed in the last 10 s --
  this run's or the last's -- written, not listed, no gap noted for it (FR-007)
- [x] T003 [US1] `app/recorder/__init__.py`, `launcher.describe`: `behind_ms` in the heartbeat,
  "N s behind" in the camera's line (FR-008)
- [x] T004 [US3] `app/version.py`; the heartbeat's `version`; the build carrying pyproject.toml
- [x] T005 [US3] `app/recorder/launcher.py`: a recorder of another version replaced; the window's
  line while it is (FR-009)
- [x] T006 [US4] `app/cameras.py`, `camera_dialog.py`: lens cameras note their lens and phone;
  `main_window.py`: a lens left out amber, not against RECORDING (FR-012)

## The phone

- [x] T007 [US1] `stream/FrameStore.kt` with its JVM tests (FR-001, FR-003, FR-004)
- [x] T008 [US1] `stream/Uplink.kt` from the store: the resend, the moments kept, `held_ms`
  (FR-002, FR-005)
- [x] T009 [US1] `capture/LensStream.kt`, `CameraStreamer.kt`: the store's folder and share,
  emptied at Stop and at each Start (what a killed app kept, too); `RtmpPublisher.kt`: the
  acknowledgements asked for every 64 KiB and read (FR-001)
- [x] T010 [US2] `CameraStreamer.open`: an open that throws tried again (FR-010)
- [x] T011 [US2] `ScreenState.hear`: a camera-wide failure clears the lenses' lines (FR-011)

## Documents and trials

- [x] T012 The contract (`held_ms`, a connection starting with frames sent before), 003's edge
  case, 005's `dropped`, `specs/app/README.md`, the android-app skill (trying a break)
- [x] T013 The emulator in tandem: the recorder killed for 10 s, no gap, each frame once
  (SC-001, SC-002); frozen for 10 s, the same -- once the phone asks for acknowledgements

## Review cycle 1

- [x] T014 `FrameStore.kt`: the last 2 s kept however short of space the phone is (FR-003)
- [x] T015 `Uplink.kt`: a keyframe asked for only for a frame the store could not keep (FR-003)
- [x] T016 `Uplink.kt`, `FrameStore.kt`: a connection without moments sends nothing kept, nothing
  again (FR-002)
- [x] T017 `Uplink.kt`: a frame's moment never set back past the one before (FR-007)
- [x] T018 `segments.py`: a later gap's reason the camera's own after a break the frames sent again
  filled; the run before's newest frame past a segment that lists none (FR-007)
- [x] T019 `main_window.py`: a lens left out keeps a port clash, a recorder that cannot start, in
  its line (FR-012)

## Review cycle 2

- [x] T020 `Uplink.kt`: only a better exchange's small step back held to the moment before; the
  recorder's clock set back taken (contract)
- [x] T021 `Uplink.kt`: `held_ms` told of the frame a connection starts at, after the wait for the
  clock (FR-005)
- [x] T022 `Uplink.kt`: at most 1,024 frames waiting for an acknowledgement (FR-001)
- [x] T023 `main_window.py`: a lens left out only by a status heard lately (FR-012)
- [x] T024 `launcher.py`, `main_window.py`: recorders of another version replaced before the window
  is shown (FR-009)
- [x] T025 `sources.py`: a connection not believed placed from `held_ms` before its first frame, a
  frame sent again on one where it was (FR-006)

## Review cycle 3

- [x] T026 `recorder/__init__.py`, `launcher.py`, `main_window.py`: this version's recorder started
  as the other is asked to stop, taking its camera over; no wait before the window shows (FR-009)
- [x] T027 `segments.py`: only a connection's first frames on listed moments taken as sent again
  (FR-007)
- [x] T028 `sources.py`: a phone's frames placed by arrival kept in order after those sent again
  (FR-006)
- [x] T029 `camera_dialog.py`: a phone's lens cameras marked with a phone no other gets (FR-012)
- [x] T030 `segments.py`: the run before's newest frame from the moments read for frames sent again

## Review cycle 4

- [x] T031 `segments.py`: a start after a segment whose times are garbled
- [x] T032 `launcher.py`: a replacement over once the heartbeat is this version's (FR-009)
- [x] T033 `sources.py`, `recorder/__init__.py`: where a phone's frames were placed elsewhere than
  their moments kept across connections, frames put after the one before too (FR-006)
- [x] T034 `recorder/__init__.py`: a camera taken over from a recorder that stopped lately; a stop
  asked meanwhile heard (FR-009)
- [x] T035 `main_window.py`: a phone status that is not a table skipped (FR-012)
- [x] T036 `recorder/__init__.py`, `segments.py`: the lag from the writer's newest frame (FR-008)
