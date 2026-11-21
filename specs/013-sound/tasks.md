# Tasks: Sound

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

- [x] T001 [US1] `app/recorder/segments.py`, `sources.py`: a stream's audio kept beside its video (FR-003)
- [x] T002 [US1] `app/sound.py`: a camera's sound from a moment, at a rate (FR-004, FR-006)
- [x] T003 [US1] `app/widgets/sound.py`, `app/main_window.py`: the sound played, the Sound switch (FR-004)
- [x] T004 [US3] `app/export.py`: the sound in the MP4 (FR-005)
- [x] T005 [US2] `stream/FrameStore.kt`, `Uplink.kt`, `RtmpPublisher.kt`, `StreamHeader.kt`, `Aac.kt`: sound kept and sent (FR-002)
- [x] T006 [US1] `capture/Microphone.kt`, `LensStream.kt`, the permission: the phone's sound (FR-001)
- [x] T007 `specs/app/README.md`; the android-app skill
- [x] T008 On the emulator: the phone's sound into a recorder, played and exported: 1229 pieces in 26.2 s, steps of 20 to 23 ms, none lost nor twice; the MP4's AAC 48 kHz beside its video (the emulator's microphone silent: SC-001 is the phone's)
- [ ] T009 On a phone (maintainer): a tone at a flash, heard at the flash (SC-001); a break (SC-002)
