# Tasks: Finding riders in the video (experimental)

One commit per task. After 001's T011 (the window shows a camera).

- [ ] T101 Settings: analysis on/off (off by default), model file, zone around the line drawn on
  the camera view. -- `feat(analysis): add the experimental analysis settings`
- [ ] T102 [US1] `app/analysis/motion.py` and the analyser process writing `activity.json`; tests
  with the swaying patch and three passes. -- `feat(analysis): index riders by motion that crosses the zone`
- [ ] T103 [US1] Stretches on the timeline, "Next rider" / "Previous rider" (PageDown/PageUp),
  progress per camera. Qt tests. -- `feat(window): jump to the next and previous rider`
- [ ] T104 Add onnxruntime (and `onnx` to the dev group for test models).
  -- `build(deps): add onnxruntime for local detection models`
- [ ] T105 [US1] `app/analysis/detector.py`: load a YOLOX ONNX model, decode, filter, suppress; the
  index uses it when a model is set. Tests with a constant-output model.
  -- `feat(analysis): find riders with a local ONNX detector`
- [ ] T106 [US2] `app/analysis/tracks.py`, suggestions, list with accept (number) and dismiss,
  journaled as interpolated. Tests with a fake detector on the test scene.
  -- `feat(analysis): suggest crossings where a rider crosses the finish line`
- [ ] T107 Document the experiment in README and `specs/app/`.
  -- `docs: describe the experimental rider finding`
