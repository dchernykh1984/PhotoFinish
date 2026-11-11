# Tasks: Several lenses of one phone, and one camera large

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## Phase 1: The code of several lenses (contract)

- [x] T001 Pairing in `specs/003-phone-camera-app/contracts/phone-stream.md`: the address alone, or
  one line per lens.
- [x] T002 [P] `app/cameras.py`: `LENSES`, `pairing_text`, with tests.
- [x] T003 [P] `android/.../pairing/Pairing.kt`: `Lens`, `LensTarget`, `Pairing.parse`, with tests.

## Phase 2: User Story 1 - the lenses streamed

- [x] T004 [US1] The dialog's lens checkboxes; `cameras()` one per lens; the code and the text
  for them all; tests in `tests/test_widgets.py`.
- [x] T005 [US1] The window adds every camera the dialog makes; test in `tests/test_window.py`.
- [x] T006 [P] [US1] `Lenses.kt`: `LensChoice.classify`, `SessionPlan.plan`, with tests.
- [x] T007 [US1] `PhoneLenses.kt`: the phone's cameras, physical ones and focal lengths; the
  concurrent pairs.
- [x] T008 [US1] `CameraStreamer`: a stream per lens, a session per camera device, the fallbacks.
- [x] T009 [US1] The screen: a line per lens, the lenses found, the code's text on several lines;
  strings in English, Russian and Kazakh.
- [x] T010 [US1] Debug `facing=front` for the emulator.

## Phase 3: User Story 2 - one camera large

- [x] T011 [US2] One camera, Ctrl+1..9, Ctrl+0, Ctrl+Up/Down; hidden cameras not decoded; tests.

## Phase 4: Polish

- [x] T012 `specs/app/README.md`, `README.md`: what the program does now.
- [x] T013 Skills `android-app` and `trying-a-camera`, both copies: trying several lenses.
- [x] T014 By hand: the emulator in tandem -- two lenses and the other camera, three recorders,
  30 fps each, every frame with its moment (2026-11-11).
- [ ] T015 By hand: the Xiaomi 17 Ultra, then the Mi 11 Ultra.
