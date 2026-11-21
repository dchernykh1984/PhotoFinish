# Implementation Plan: The start protocol's numbers for the number reader

**Spec**: [spec.md](spec.md)

## Shape

```
app/start_protocol.py      the numbers of a start protocol file; read again when it changes
app/analysis/numbers.py    the surest reading of a start number, when there are start numbers
app/analysis/analyzer.py   the protocol of the session, read again from segment to segment
app/main_window.py         "Start protocol...": the file chosen, its name and count shown
```

- **Compared loosely.** A reading and a start number are compared upper case, leading zeros of a
  run of digits left out ("007" is 7), as SportPhotoIndexer compares them; the number given is
  the protocol's spelling.
- **Read again** when the session's path, or the file's size or time, changes: a stat a segment.

## Tests

The numbers of a StartProtocolMaker line, a relay's stages, a header line, the encodings; the
reader's choice with and without a protocol; the analyser reading a changed protocol; the
window's button and its label.
