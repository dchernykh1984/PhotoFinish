# Tasks: What the phone hits, on the laptop

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## The phone

- [x] T001 [US1] `diagnostics/PhoneLog.kt`, `LogMessages.kt` with their JVM tests (FR-003, contract)
- [x] T002 [US1] `diagnostics/LogSender.kt` with its JVM tests (FR-002)
- [x] T003 [US1] `diagnostics/ProcessLog.kt`, `Crashes.kt`, `StatusLog.kt` (FR-001)
- [x] T004 [US1] `MainActivity.kt`, `CameraStreamer.kt`, `LensStream.kt`: the log made, sent, and fed
  (FR-001, FR-002)

## The recorder and the window

- [x] T005 [US1] `app/recorder/phone_log.py`, `clock_sync.py`, `__init__.py`: the lines kept, the
  answer, the heartbeat's last word (FR-004, FR-005, FR-006)
- [x] T006 [US2] `app/main_window.py`: the phone's last word in a camera's line (FR-005)

## Documents and trials

- [x] T007 The contract, `specs/app/README.md`, the android-app skill (reading `phone.log`),
  CLAUDE.md and AGENTS.md
- [x] T008 The emulator in tandem (SC-001, SC-002, SC-003)
