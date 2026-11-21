# Tasks: Playing faster, slower and backwards

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

- [x] T001 [US1] `app/playback.py`: the rate, either direction (FR-001, FR-002, FR-003)
- [x] T002 [US2] `app/decoder.py`: the frames decoded lately kept (FR-005)
- [x] T003 [US1] [US2] `app/main_window.py`: "< Play", "Play >", the speed buttons; Qt tests (FR-001 to FR-004)
- [x] T004 `specs/app/README.md`
- [x] T005 Backwards at x1 on a 1440p 60 fps recording, frames counted (SC-003): 265 a second against 488 forwards, 25 without the frames kept
