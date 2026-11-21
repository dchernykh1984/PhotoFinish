# Tasks: Nothing the phone kept is lost

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## The phone

- [x] T001 [US1] `stream/FrameStore.kt`: the index on disk, read back, synced at keyframes; the
  hold by the wall clock for frames read back; no cap but the free space less 10 GB (FR-001, FR-005)
- [x] T002 [US1] `stream/KeptStore.kt`: a kept stream's header file, written and read back (FR-001)
- [x] T003 [US1] `stream/Uplink.kt`: a stream of kept frames alone; the turn at an address (FR-002, FR-003)
- [x] T004 [US1] `capture/Backlog.kt`: read back at the start, handed over, one an address, removed
  once sent, discard (FR-002, FR-003, FR-004)
- [x] T005 [US2] `LensStream.kt`, `KeptStreams.kt`, `CameraStreamer.kt`: a folder a stream; Stop,
  another choice, release and a dead encoder hand over; Discard (FR-003, FR-004)
- [x] T006 [US3] `capture/Priority.kt` and the uplink's wait for the first lens (FR-007)
- [x] T007 [US2] `SendingService.kt`, the manifest, the notification (FR-006)
- [x] T008 [US4] `status/PhoneStatus.kt`, `PhoneStatusReader.kt`: `free`, `unsent_ms`, `unsent_mb` (FR-008)
- [x] T009 [US2] the screen: what is unsent, Discard and its confirmation; ru and kk strings (FR-010)

## The laptop

- [x] T010 [US4] `app/phone_status.py`: free storage, amber under 30 GB, red under 10 GB (FR-009)
- [x] T011 [US4] `app/catch_up.py`, `launcher.describe`, `main_window.py`: the video on the phone,
  its bar and estimate in the camera's line (FR-009)

## Documents and trials

- [x] T012 the contract (`003-phone-camera-app/contracts/phone-stream.md`): the new readings, `held_ms`
  across a restart; `specs/007` FR-004 and its Stop assumption superseded; `specs/app/README.md`
- [x] T013 the `android-app` skill, both copies: trying a kill, a Stop and the first lens first
- [x] T014 On the emulator: the app killed with frames kept, then started (SC-001); Stop (SC-002);
  the first lens first (SC-003)
- [ ] T015 On a phone (maintainer): the battery run down mid-stream, the phone charged and started
