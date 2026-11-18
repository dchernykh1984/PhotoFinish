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
- [ ] T015 By hand: the Xiaomi 17 Ultra, then the Mi 11 Ultra. On 2026-11-17 the Xiaomi 17
  Ultra's four lenses at 2560x1440 and 60 fps gave no frame, its camera failing: the phase below.

## Phase 5: Lenses the cameras fail with, and the dialog's advice (2026-11-17, PR #30)

- [x] T016 [US1] `LensFallback.kt`, with its JVM tests: which failures are the lenses', which lens
  goes -- of the camera that failed, the silent first, never the first --, one an open, settled
  once every lens gave frames for 10 s, whether the cameras are made again (FR-005).
- [x] T017 [US1] `CameraStreamer`: the failures told to the fallback, the no-frame check, the
  lenses left out of each open and said why, the settling, the room shared (FR-005).
- [x] T018 [US1] `SessionOutputs`, `CameraStreamer`: the frame rate in the session and in the
  question to the camera, from Android 15 (FR-005).
- [x] T019 [US1] The dialog's advice past two lenses, Main and Telephoto; its Qt test (FR-001).
- [x] T020 The spec, `specs/app/README.md`, the android-app skill.
- [x] T021 By hand: the emulator in tandem -- three lenses streamed with the rate in the session.
- [x] T022 By hand: the Xiaomi 17 Ultra with four lenses, the lenses left out until the rest
  stream, each said in `phone.log`. The maintainer, 2026-11-18: the cameras failed 1.6 s in, the
  ultra-wide left out from then on, Main, Telephoto and Front at 2560x1440 and 60 fps after.

## Phase 6: A lens that stops, the front's size, the screen leaving (2026-11-18)

- [x] T023 [US1] `LensFallback.kt`, with its JVM tests: a lens that gave frames and then none --
  early, itself left out, the first lightening the load as an error does; later, every lens kept;
  again within a minute, left out, the first waited for beside others and tried again a minute on,
  alone opened again; the other camera's lens stopping later waited for; a lens waited for that
  gives frames watched again; timed by its last frame (FR-005).
- [x] T024 [US1] `CameraStreamer`, `LensStream`: each lens's last frame, watched each second; 3 s
  without one is its camera lost (FR-005).
- [x] T025 [US1] The dialog's advice for the Front beside a back lens, 1920x1440 or less; its Qt
  test (FR-001).
- [x] T026 [US1] `CameraStreamer`, `CameraScreen`: the screen leaving closes the cameras at once,
  waited for, the lenses' streams sending what they kept and saying so; a surface made again opens
  them again (FR-005).
- [x] T027 By hand: the emulator, one lens -- Home: the cameras closed in `phone.log`, no failure,
  the frames kept sent; back: streaming again; 2.5 min without a lens taken for stopped. A lens
  that stops could not be made there: its image gives no root to stop the camera's service.
- [ ] T028 By hand: a phone whose lens stops mid-stream, its camera opened again.
