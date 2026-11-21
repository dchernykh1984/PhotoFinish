# Implementation Plan: A camera's video as one file

**Spec**: [spec.md](spec.md)

## Shape

```
app/export.py           a camera's pieces into MP4 files: packets copied, timed by their moments,
                        a new file where the format changes; progress and cancel
app/main_window.py      "Export video...": the cameras to tick, the folder, a worker and its progress
```

- **Timed by the moments.** Each piece's `.times` gives a frame's moment by its timestamp; a packet
  whose moment is not listed -- sent again, written for the frames after it to decode -- is
  skipped, as the piece before holds it. A file's time base is a millisecond; its first frame is
  at 0, the others at their moment less the first's; decode times follow presentation times less
  the piece's own offset between the two, never going back.
- **One format a file**: the codec, size and header of each piece's stream; another starts a new
  file.
- **Written aside**: `<name>.mp4.part`, renamed once whole; removed on Cancel or failure.

## Tests

One camera, two pieces: one file, every frame, its times; a format change: two files; a name
taken: a number; Cancel: no file left; the window's button: files for the cameras ticked.
