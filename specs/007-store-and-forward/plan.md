# Implementation Plan: A network break costs no frame

**Spec**: [spec.md](spec.md) | **Contract**: [../003-phone-camera-app/contracts/phone-stream.md](../003-phone-camera-app/contracts/phone-stream.md)

## Shape

```
android/.../stream/FrameStore.kt     a lens's frames on the phone's storage: kept, read, sent again
android/.../stream/Uplink.kt         frames from the store; a loss sends the last 6 s again; held_ms
android/.../capture/LensStream.kt    the store's folder and share; the frames' clock for held_ms
android/.../capture/CameraStreamer.kt  each lens's store; what a killed app kept removed at a Start;
                                     an open that throws is tried again (glue)
android/.../ui/ScreenState.kt        a camera-wide failure clears the lenses' lines (glue)
android/.../stream/RtmpPublisher.kt  the bytes it sends counted, the acknowledgements asked for and read
app/recorder/sources.py              held_ms read; a kept frame's moment believed
app/recorder/segments.py             a frame sent again written, not listed
app/recorder/__init__.py             the heartbeat's behind_ms and version
app/version.py                       the program's version, from pyproject.toml
app/recorder/launcher.py             a recorder of another version replaced; "N s behind"
app/cameras.py, camera_dialog.py     a lens camera notes its lens and its phone
app/main_window.py                   the replacing line; a lens left out: amber, banner green
.github/workflows/build.yml          pyproject.toml carried by the frozen build
```

- **Everything through the store.** The uplink no longer has a queue of 2 s that empties when the
  network falls behind: every frame goes to the store, and the uplink sends from it at the
  network's pace. A break, a slow network and a recorder restarting are then one case. The store
  is one file per keyframe run (a second at the stream's keyframe interval), the frames' bytes in
  it and their index -- capture time, keyframe, moment, place -- in memory: the store is not kept
  across an app restart (FR-004), so the index needs no file. Files the recorder has acknowledged
  reading go, 2 s on; files are only appended, read and deleted.
- **The recorder says what it has read.** FFmpeg's listener acknowledges every half window it
  reads, a megabyte by default -- a slow stream would hear none for long, and the emulator's did
  not: asked for a window of 128 KiB, it acknowledges every 64 KiB. The publisher counts the bytes
  it writes, the handshake and commands too, so never fewer than FFmpeg's count, and unwraps the
  acknowledgement's 32 bits; the uplink matches it to the frames sent and tells the store the
  newest read.
- **The moment is fixed when a frame is kept**, with the offset of that time, slewed in capture
  order as before. A frame sent again carries the moment it carried the first time: the
  recorder's test "at or before the newest frame" is exact, and a lost clock exchange during a
  break changes nothing.
- **A connection after a loss starts 2 s before the newest frame acknowledged**, at a keyframe --
  6 s before the newest sent without acknowledgements: the recorder writes what it has already,
  unlisted, as the frames after it need it to decode, found by its moment among those it listed
  in the last 10 s, the run before's too (FR-007). A connection is stamped
  when its first frame has a moment; a clock in step during the first 10 s of an unstamped one
  still makes a new connection, which starts at the first keyframe with a moment.
- **held_ms** is in `onMetaData`: the capture clock now minus the first frame's capture time.
  The recorder widens its belief by it; nothing else of the contract changes. An older recorder
  places such a connection by arrival, all of it late by what its first frame was kept: the two
  programs are updated together.
- **The version** is pyproject.toml's, which release-please already bumps: the window and its
  recorders read the same file (the repository's, or the copy the build carries), so they agree
  unless an update came between them. Unreadable, it is "": an older build's window replaces
  nothing.
- **Replacing a recorder**: the watchdog that finds one of another version asks it to stop and
  starts its own once its heartbeat says it stopped or went stale; a phone keeps its frames
  meanwhile (US1).

## Tests

- JVM: the store (keep, read, the 6 s kept behind, rewind to a keyframe, full, clear, held); the
  uplink (frames from the store at the network's pace, a loss sending the last 6 s again, the same
  moments, held_ms, a stamped connection after an unstamped one starting at a stamped keyframe).
- pytest: held_ms believed and not beyond it; a frame sent again written and not listed, the
  frames after it decoded; behind_ms and version in the heartbeat; the version read; the watchdog
  replacing; describe's "N s behind"; the build carrying pyproject.toml; lens notes; the window's
  replacing line, its lens left out and the banner.
- By hand: the emulator in tandem, the recorder killed for 10 s (SC-001, SC-002); the Xiaomi 17
  Ultra with the maintainer.
