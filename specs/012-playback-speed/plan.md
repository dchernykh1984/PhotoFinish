# Implementation Plan: Playing faster, slower and backwards

**Spec**: [spec.md](spec.md)

## Shape

```
app/playback.py         the frame due by the clock at a rate: signed, x1/16 to x16 either way;
                        a gap jumped over either way; None past either end
app/decoder.py          the frames decoded lately kept, up to a size: a step back, or playing
                        backwards, takes them from there instead of decoding from the keyframe
app/main_window.py      "Play <", "Play >", the speed buttons and their label; the timer asks
                        playback for the frame due at the rate
```

- **The clock.** Playing keeps the clock and the moment it went on from; the moment due is that
  moment plus the time since, times the rate. A change of rate or direction while playing goes
  on from the frame shown, so the picture never jumps.
- **Backwards** shows the first frame at or after the moment due, the mirror of forwards' last
  at or before it; a gap of more than a second before it is jumped over to the frame on its far
  side.
- **The decoder's keep**: frames decoded are kept, newest last, up to 96 MB a camera -- some 17
  frames of 1440p, 30 of 1080p --; a request for one kept is answered from it; the keep is
  emptied when another segment is opened. Going backwards, a seek decodes from the keyframe to
  the frame asked and keeps the frames on the way.

## Tests

The rate's frames due either way, its gaps and ends; the decoder's keep answering a step back
without a seek, its size bound; the window's buttons, labels and limits, playing backwards to
the first frame, Stop and Pause in both directions.
