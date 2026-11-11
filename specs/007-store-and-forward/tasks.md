# Tasks: A network break costs no frame

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## The recorder and the window

- [ ] T001 [US1] `app/recorder/sources.py`: `held_ms` from the stream's metadata; a phone's moment
  believed up to it older (FR-006)
- [ ] T002 [US1] `app/recorder/segments.py`: a frame at or before the newest of the run written,
  not listed (FR-007)
- [ ] T003 [US1] `app/recorder/__init__.py`, `launcher.describe`: `behind_ms` in the heartbeat,
  "N s behind" in the camera's line (FR-008)
- [ ] T004 [US3] `app/version.py`; the heartbeat's `version`; the build carrying pyproject.toml
- [ ] T005 [US3] `app/recorder/launcher.py`: a recorder of another version replaced; the window's
  line while it is (FR-009)
- [ ] T006 [US4] `app/cameras.py`, `camera_dialog.py`: lens cameras note their lens and phone;
  `main_window.py`: a lens left out amber, not against RECORDING (FR-012)

## The phone

- [ ] T007 [US1] `stream/FrameStore.kt` with its JVM tests (FR-001, FR-003, FR-004)
- [ ] T008 [US1] `stream/Uplink.kt` from the store: the resend, the moments kept, `held_ms`
  (FR-002, FR-005)
- [ ] T009 [US1] `capture/LensStream.kt`, `CameraStreamer.kt`, `MainActivity.kt`: the store's
  folder and share, emptied at Stop and at the start
- [ ] T010 [US2] `CameraStreamer.open`: an open that throws tried again (FR-010)
- [ ] T011 [US2] `ScreenState.hear`: a camera-wide failure clears the lenses' lines (FR-011)

## Documents and trials

- [ ] T012 The contract (`held_ms`, a connection starting with frames sent before), 003's edge
  case, 005's `dropped`, `specs/app/README.md`, the android-app skill (trying a break)
- [ ] T013 The emulator in tandem: the recorder killed for 10 s, no gap, each frame once
  (SC-001, SC-002)
