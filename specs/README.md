# Specifications

PhotoFinish is developed spec-first for changes to its file formats, what the referee sees
and how it works with the other timing tools, with
[Spec Kit](https://github.com/github/spec-kit), whose skills both coding agents here
(Claude Code and Codex) carry.

```
specs/
  app/                        the program as it works today, from the first feature on
  <NNN>-<short-name>/         one feature
    spec.md                   what and why, for the referee and the readers of the files
    plan.md, tasks.md         how it will be built, once the spec is reviewed
```

The principles every plan is checked against are in
[`.specify/memory/constitution.md`](../.specify/memory/constitution.md).

**Keep `app/` true.** A change that alters described behaviour updates it in the same pull
request.

## Features

- [001-video-refinement](001-video-refinement/spec.md): live finish video and the referee's list
  of crossings.
- [002-video-analysis](002-video-analysis/spec.md): finding riders in the video (experimental).
- [003-phone-camera-app](003-phone-camera-app/spec.md): PhotoFinish Camera, the phone app that
  streams to PhotoFinish with each frame's moment.
- [004-phone-lenses](004-phone-lenses/spec.md): several lenses of one phone, the front camera
  among them, recorded at once; one camera large, and switching between cameras.
- [005-phone-status](005-phone-status/spec.md): the phone's battery, heat, Wi-Fi and dropped
  frames, shown on the laptop beside the recording banner.
- [006-numbers-and-one-line](006-numbers-and-one-line/spec.md): riders' numbers read, every
  camera's crossings as one, one finish line for all cameras (issue #21).
