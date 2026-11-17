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

## Review cycle 1

- [x] T009 The phone's gaps passed over, each message saying the line before it (contract)
- [x] T010 `phone_log.py`: the last runs each; a time of no computer's; a new file's run
- [x] T011 `clock_sync.py`: the log on a thread of its own
- [x] T012 `PhoneLog.kt`: the app's own lines mirrored alone; the left-out count told once its
  second is over
- [x] T013 `StatusLog.kt`: a status said again within a minute counted
- [x] T014 `LogSender.kt`: one message a round to a recorder that never answered; the recorders of
  the kept code, no activity held

## Review cycle 2

- [x] T015 `phone_log.py`: each turn of another run marked; every run's last line found at a start;
  the last word ended by the next line; `clock_sync.py`: the log's answers a budget of their own
- [x] T016 `StatusLog.kt`: where each lens came to rest told; its memory of words kept to 64
- [x] T017 `ProcessLog.kt`: the system log read again when it ends; `LogSender.kt`: recorders by the
  code's host and port; `LensStream.kt`: its log given

## Review cycle 3

- [x] T018 `phone_log.py`: the last word kept till the phone says otherwise, its age past a minute;
  `clock_sync.py`: a reset of Windows' no pause; the log's thread only with a log; `__init__.py`: a
  phone log for phones alone
- [x] T019 The log's notes about itself as the system log's; `ProcessLog.kt`: read again from after
  its newest line, never again when it ends at once; `LogSender.kt`: a quiet recorder's name found
  again; `Diagnostics.kt`: the lenses logged once

## Review cycle 4

- [x] T020 `phone_log.py`: the last word kept till the next warning or error, its age by the
  phone's clock; the file read at the first message
- [x] T021 `main_window.py`: the last word from a running recorder alone, not on a lens left out
- [x] T022 `LogSender.kt`: a name looked up when due; `ProcessLog.kt`: read only by lines of the
  log; the round's lines walked by index
