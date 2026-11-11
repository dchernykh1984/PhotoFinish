# Implementation Plan: Riders' numbers, every camera's crossings together, one finish line

**Spec**: [spec.md](spec.md)

## Shape

```
app/interpolation.py            camera_line, own_line: the common line and a camera's own
app/analysis/__init__.py        settings: "crossings"; model_in_use; zone on the camera's line
app/analysis/analyzer.py        the line a camera times on; the number read at a crossing
app/analysis/numbers.py         NumberReader: text found (DB) and read (CTC), digits kept
app/analysis/models.py          the number reader's two models, pinned by URL, size, SHA-256
app/analysis/suggestions.py     gathered: one suggestion per crossing several cameras saw
app/main_window.py              Edit finish line, This camera only, Numbers and crossings
```

- **No OpenCV** (002): the detector's map is parted into its connected pieces with a flood fill
  over the few pixels of text; pictures are scaled by FFmpeg (`VideoFrame.reformat`).
- **Read once, at the crossing**: the sample frame after the line, in the rider's box -- not every
  frame -- so the reader costs a fraction of a second per rider.
- **Merged in the window**: each analyser keeps its own camera's suggestions as before; the window
  lists the crossings, so a camera added or removed changes nothing written.

## Tests

- pytest: `camera_line` and the old sessions; the analyser timing on the common line; the edit mode
  and both kinds of line (Qt); the switches; `gathered`; `NumberReader` on fake sessions (the map's
  pieces, CTC with repeats and blanks, digits kept, confidence); the models pinned.
- By hand: the pinned models read numbers drawn in a picture (247, 1305, 58: all read).
