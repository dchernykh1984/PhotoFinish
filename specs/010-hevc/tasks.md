# Tasks: H.265, as an experiment

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

- [ ] T001 [US1] `app/widgets/camera_dialog.py`, `app/cameras.py`: the codec row and the code's line (FR-001)
- [ ] T002 [US1] `app/recorder/frame_time.py`, `sources.py`: H.265 read for moments and status (FR-004)
- [ ] T003 [US1] `pairing/Pairing.kt`: the codec line (FR-002)
- [ ] T004 [US1] `capture/FormatChoice.kt`, `CameraFormats.kt`: the codec in the format, H.265's bitrate,
  H.264 when the encoder does not take it, said (FR-002)
- [ ] T005 [US1] `stream/Hevc.kt`, `Sei.kt`, `RtmpPublisher.kt`, `Uplink.kt`, `LensStream.kt` (FR-003)
- [ ] T006 the contract; `specs/app/README.md`; the android-app skill
- [ ] T007 On the emulator: H.265 to a recorder (SC-001)
- [ ] T008 On the phones (maintainer): two lenses of H.265 on the Mi 17 Ultra and the Mi 11 Ultra
