# Implementation Plan: Finding riders in the video (experimental)

**Branch**: `feat/live-video-editor` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-video-analysis/spec.md`; builds on
`specs/001-video-refinement/plan.md`.

## Summary

An analyser process per camera reads closed segments, samples frames and writes, next to each
segment, where a rider is in view: from motion that travels across a zone around the finish line,
or from a person/bicycle detector when the referee installed an ONNX model. The window shows the
stretches on the timeline, jumps between them, and lists crossings the detector suggests where a
rider's front crosses the finish line. Everything is off by default.

## Technical Context

**Language/Version**: Python 3.14

**Primary Dependencies**: numpy (motion), onnxruntime 1.31 (detector; CPU), PyAV (decoding) --
onnxruntime added with this feature; wheels checked for all five release platforms

**Storage**: `video/<camera>/<segment>.activity.json` per segment; `video/<camera>/suggestions.jsonl`

**Testing**: synthetic scenes from the test camera (swaying patch, passing figure); a constant-output
ONNX model built in the tests with `onnx.helper` (dev dependency) to check loading and decoding --
or, if `onnx` has no wheel for Python 3.14 on the CI runner, the same few-hundred-byte model
generated once by a script in `tests/` and committed; a fake detector for the pipeline

**Performance Goals**: index within 10 s of recording on two cameras on a laptop CPU, sampled at
5 fps for motion and 2 fps for the detector

**Constraints**: principle VI: analysis never makes recording or the window wait; models are local
files

## Constitution Check

| Principle | How the plan meets it |
| --- | --- |
| II, VI | The analyser is a separate, lower-priority process reading closed segments only; its failure is reported and ignored by recording and timing. |
| III, V | An accepted suggestion becomes an ordinary output change journaled with model, frames and fraction; it is marked interpolated. |
| Constraints: offline | The model is a file the referee downloads beforehand; nothing is fetched. |
| VII | Motion, decoding of detector output, tracking and line crossing are Qt-free and unit-tested. |

No violation.

## Design

- **Motion** (`app/analysis/motion.py`): grey frames at 160 px wide; difference to a running
  background inside the zone; pixels above a threshold form a mask; a stretch is active while the
  mask's area exceeds 0.5% of the zone and its centroid travels at least a quarter of the zone's
  width across the finish line's direction within 2 s. Leaves move in place, so they fail the
  travel test.
- **Detector** (`app/analysis/detector.py`): YOLOX-format ONNX (`yolox_s.onnx`, Apache-2.0,
  downloaded by the referee from the YOLOX releases); letterbox to the model's input, decode grids
  at strides 8/16/32, keep classes person (0) and bicycle (1) above 0.4, non-maximum suppression at
  0.45.
- **Tracker** (`app/analysis/tracks.py`): greedy IoU matching between sampled frames; a track's
  front is the box edge nearest the line in its direction of travel.
- **Suggestions**: when a track's front changes side of the finish line between two samples, the
  recorded frames between them are decoded and the detector re-run on them; the two frames around the
  crossing give the time by `app/interpolation.py`.
- **Analyser process** (`--analyzer <camera>`, a `QProcess` child of the window: it may die with
  it) writes `activity.json` per segment and appends to `suggestions.jsonl`; progress in
  `analyzer.json` like the recorder's heartbeat.

## Project Structure

```text
app/analysis/
  __init__.py      analyser main loop, progress file
  motion.py        motion stretches
  detector.py      ONNX detector and YOLOX decoding
  tracks.py        tracks and line crossings
tests/test_motion.py, test_detector.py, test_tracks.py, test_analyzer.py, window tests
```

## Complexity Tracking

Empty.
