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
