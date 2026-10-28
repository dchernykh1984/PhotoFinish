# Implementation Plan: Live finish video and the referee's list of crossings

**Branch**: `feat/live-video-editor` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-video-refinement/spec.md`

## Summary

A recorder process per camera captures it with PyAV and writes short Matroska segments with a
sidecar of frame times; it keeps running if the window goes. The window indexes the closed
segments, decodes any frame on a worker thread and shows one or more cameras on a zoomable timeline
while recording goes on. Beside the video, the input list (one chronometer file, read only) and the
output list (the referee's, written to a file of its own with a journal) follow the video's time.
The referee adds crossings from frames, changes times and numbers, removes false crossings, reads
times between frames like a caliper, and aligns cameras and the timing source by shared events.

## Technical Context

**Language/Version**: Python 3.14

**Primary Dependencies**: PySide6 (window, `QMediaDevices` for camera names), PyAV 19 (capture,
recording, decoding), numpy (frames, indexes). Added with this feature, wheels checked for all five
release platforms.

**Storage**: files in the event folder (see [data-model.md](data-model.md))

**Testing**: pytest with the offscreen Qt `win` fixture; the test camera and generated files; real
recorder processes in tests; coverage gate 90% on the Qt-free modules

**Target Platform**: portable builds for Windows (x64, arm64), macOS (Apple Silicon), Linux (x86_64,
aarch64)

**Project Type**: desktop application with helper processes

**Performance Goals**: newest frame viewable within 2 s of capture; a seek anywhere in a one-hour
recording shows its frame within 0.5 s; two 720p30 cameras recorded on a laptop

**Constraints**: constitution I (input read only), III (every change on disk and journaled), V
(sub-frame times labelled), VI (recording outlives the window); no internet

**Scale/Scope**: up to 4 cameras, 12-hour recordings, a few thousand crossings

## Constitution Check

| Principle | How the plan meets it |
| --- | --- |
| I. The source is never touched | The input is opened read-only, polled, never locked; tests compare its bytes after every scenario. |
| II. Timing never depends on PhotoFinish | No chronometer code runs here; the exchange is the input and output files. |
| III. Every change is on disk and traceable | Atomic output writes, `state.json` for origins, an append-only journal with frames, method and offsets. |
| IV. The line format is a shared contract | Lines read with the chronometers' encodings, taken lines keep their bytes, times written the desktop way, the output read by FinishProtocolGenerator's rule in a test. |
| V. Sub-frame time, labelled | Interpolated and hand-picked times are marked in the list and recorded with their frames and fraction; no extrapolation. |
| VI. Recording outlives the editor | Detached recorder processes controlled through files; closed segments only are read. |
| VII. Tests | Qt-free modules for lines, output, input alignment, recording, indexes, interpolation, session; Qt tests for the window; the test camera makes every video. |
| VIII. Plain history | One commit per task below. |

No violation.

## Project Structure

### Documentation (this feature)

```text
specs/001-video-refinement/
  spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
  contracts/
    output-and-journal.md
    recorder.md
```

### Source Code (repository root)

```text
app/
  main.py               --recorder <camera> runs a recorder instead of the window
  main_window.py        layout and wiring only
  lines.py              crossing lines, times, reading with encodings
  session.py            data/session.json
  output_list.py        output file, state, journal, external changes
  input_follow.py       input polling and alignment with the input as last taken
  cameras.py            connections, presets, settings validation
  recorder/
    __init__.py         recorder main loop, heartbeat, stop request, disk checks
    sources.py          open a connection as frames or packets (usb, rtsp, rtmp, file, test)
    segments.py         segment writer with the times sidecar
    testcam.py          synthetic scenes: clock, moving bar, flash, swaying patch
    launcher.py         start detached, attach by heartbeat, restart with backoff
  video_index.py        closed segments and frame times per camera, gaps
  decoder.py            decode a frame by camera and time (used on a worker thread)
  interpolation.py      finish line geometry and the caliper reading
  widgets/
    camera_view.py      a frame, the finish line, clicked points
    timeline.py         zoomable timeline: gaps, crossings, frames when zoomed in
    lists.py            input and output list models and views
tests/
  one test module per app module, plus window tests through `win`
```

**Structure Decision**: single project. Everything that is not drawing goes to Qt-free modules the
coverage gate measures; widgets are thin and tested through `win`; the recorder is a package the
same executable runs with `--recorder`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| Helper processes (recorder per camera) | Principle VI: a window crash must not cost frames | A thread dies with the window; a `QProcess` child is killed with it |
