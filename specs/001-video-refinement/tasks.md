# Tasks: Live finish video and the referee's list of crossings

Each task is one commit with the message shown; the tests that prove a task are part of it. Before
each commit: `uv run pre-commit run --all-files` and `uv run pytest`.

## Phase 1: lines, session, output (US3, US4)

- [ ] T001 Add PyAV and numpy; prove they import and that the build collects them.
  -- `build(deps): add PyAV and numpy for video`
- [ ] T002 `app/lines.py`: parse and format crossing lines and times (summer-time option), read a
  file's complete lines with the encodings of the older tools. -- `feat(lines): read and write crossing lines and times`
- [ ] T003 `app/session.py`: load and save `data/session.json` through `app_path`, defaults,
  unknown keys kept, written in one step (temporary file and rename) because recorders read it
  while the window writes it. -- `feat(session): keep the session next to the program`
- [ ] T004 [US4] `app/output_list.py`: output lines in time order, atomic writes, `state.json`,
  journal, add/time/number/remove, outside changes kept in a backup and journaled.
  -- `feat(output): keep the referee's crossings in their file with a journal`
- [ ] T005 [US3] `app/input_follow.py`: poll the input, align it with the input as last taken, take
  new lines, highlight changed ones, mark removed ones, copy by hand; persisted in the session.
  -- `feat(input): take new chronometer lines and hold back changed ones`

## Phase 2: recording (US1, US8)

- [ ] T006 [US1] `app/recorder/segments.py` and `testcam.py`: segment writer (2 s, keyframe cuts,
  `.times` sidecar, rename on close, gaps) fed by the test camera; `mpeg4` encoding.
  -- `feat(record): write a camera in short segments with each frame's time`
- [ ] T007 [US1] `app/recorder/__init__.py`: recorder main loop, heartbeat file, stop request, low
  and full disk, reconnect with backoff; `--recorder` in `app/main.py`. Tests run a real recorder
  process with the test camera. -- `feat(record): run a camera's recorder as a process of its own`
- [ ] T008 [US1] `app/recorder/launcher.py`: start detached, attach to a fresh heartbeat, restart a
  dead recorder after 1-30 s, stop through `stop.request`. Tests kill the parent and check the
  recording continues. -- `feat(record): keep recording when the window is gone`
- [ ] T009 [US8] `app/recorder/sources.py` and `app/cameras.py`: USB (avfoundation, dshow,
  video4linux2), RTSP, RTMP listen, file as live; presets labelled untested. Tests: file as live,
  RTMP pushed from the same process, settings validation.
  -- `feat(cameras): connect USB, RTSP, RTMP and file cameras with the owner's presets`

## Phase 3: viewing (US1)

- [ ] T010 [US1] `app/video_index.py` and `app/decoder.py`: closed segments, frame times, gaps;
  decode the frame nearest a time. Tests measure, with the test camera, that a frame is indexed
  within 2 s of capture and that a seek in a one-hour index decodes within 0.5 s (SC-006; a looser
  bound on CI runners, the real one on the maintainer's laptop).
  -- `feat(video): index recorded frames and decode any of them`
- [ ] T011 [US1] Camera view, zoomable timeline, transport and Live, decode worker, keyboard
  stepping; camera list with add/remove and recorder state. Qt tests.
  -- `feat(window): scroll a camera while it records`

## Phase 4: timing (US2, US3, US4)

- [ ] T012 [US2] Number field and Enter: a crossing at the current frame, finish-mode switch. Qt
  tests. -- `feat(window): add a crossing at the current frame from the keyboard`
- [ ] T013 [US3] Input and output lists following the video, selection seeks, highlights, "Copy to
  output". Qt tests. -- `feat(window): show the input and output lists at the video's time`
- [ ] T014 [US4] Set time from frame, type a time, change a number, remove with confirmation. Qt
  tests. -- `feat(window): correct a crossing's time or number and remove a false one`

## Phase 5: precision and alignment (US5, US6, US7)

- [ ] T015 [US5] `app/interpolation.py`; finish line drawn on the camera view; two clicked points
  give the offered time; refusal on one side; marks in the list.
  -- `feat(precision): read a crossing time between two frames like a caliper`
- [ ] T016 [US5] Click between frames on the zoomed timeline.
  -- `feat(precision): pick a time between two frames on the zoomed timeline`
- [ ] T017 [US6] Several cameras at one moment; align them on a shared event.
  -- `feat(cameras): show several cameras at one moment and align them on a shared event`
- [ ] T017a [US8] A camera's own recording opened after the race (FR-007, US8 scenario 4): its
  frames placed by the file's creation time, aligned like any camera, the file never written.
  -- `feat(cameras): open a camera's own recording after the race`
- [ ] T018 [US7] Source offset from an input line and its frame, applied both ways and journaled.
  -- `feat(align): align the video with the timing source`

## Phase 6: build and documentation

- [ ] T019 Build workflow: collect PyAV's libraries, smoke-run `--recorder` with the test camera
  from the frozen app on every platform. -- `ci(build): check that the frozen app records the test camera`
- [ ] T020 README, CLAUDE.md, AGENTS.md (no more "corrected copy"), `specs/app/` describing the
  program as built, the shipping skill's example. -- `docs: describe the live editor`

## Dependencies

T001 -> T002 -> T003 -> T004 -> T005. T001 -> T006 -> T007 -> T008 -> T009. T009 -> T010 -> T011
-> T012 -> T013 -> T014 -> T015 -> T016 -> T017 -> T018. T019 after T008. T020 last.
