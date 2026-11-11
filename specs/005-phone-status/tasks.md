# Tasks: What may stop a phone's stream, shown on the laptop

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

- [x] T001 The status SEI in `specs/003-phone-camera-app/contracts/phone-stream.md`.
- [x] T002 [P] `PhoneStatus`, `Sei.phoneStatus`, with JVM tests.
- [x] T003 `PhoneStatusReader`; the uplink writes the status on keyframes; tests.
- [x] T004 [P] `frame_time.phone_status`, with tests.
- [x] T005 `Stream.phone`, the heartbeat's `phone`, with tests.
- [x] T006 [P] `app/phone_status.py`: readings and levels, with tests.
- [x] T007 The window's line per camera under the banner; Qt test.
- [x] T008 `specs/app/README.md`, `README.md`, the `trying-a-camera` skill.
- [x] T009 By hand: the emulator in tandem, its battery set low: three lenses' lines red at 9 %
  in the window, attached to their recorders (2026-11-11).
- [ ] T010 By hand: the Xiaomi 17 Ultra on its own Wi-Fi and as the hotspot.
