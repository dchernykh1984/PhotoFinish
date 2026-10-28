# Research: live finish video and the referee's list of crossings

## 1. Video library: PyAV with its bundled FFmpeg

- **Decision**: PyAV 19 (FFmpeg 9) for capture, recording and decoding; numpy for frames.
- **Rationale**: checked on 2026-10-29 in the 19.0.2 wheels: abi3 wheels for macOS arm64, Linux
  x86_64/aarch64 and Windows x64/arm64; capture devices `avfoundation` (macOS), `dshow` (Windows,
  both architectures), `video4linux2` (Linux); the `rtsp` demuxer; the RTMP protocol in listen mode
  (`av.open("rtmp://0.0.0.0:1935/live/x", options={"listen": "1"})` waits for a client);
  encoders `mpeg4`, `mjpeg`, `libx264`, `libvpx`. One library covers every camera connection.
- **Alternatives**: OpenCV (rejected: no Windows on ARM wheel); Qt Multimedia for capture
  (rejected for recording: no per-frame timestamps or segment control; kept for listing the USB
  cameras by name, which PyAV cannot do); calling the `ffmpeg` program (rejected: a second binary to
  ship per platform).
- **Licensing note**: the wheels report FFmpeg as LGPL v3 but also link libx264 and libx265 (GPL).
  PhotoFinish does not use them -- it encodes with the native `mpeg4` encoder -- but the portable
  builds carry the libraries. Raised with the maintainer in issue #49.

## 2. Recording in short Matroska segments with a time sidecar

- **Decision**: each camera is written to `video/<camera>/<YYYYmmdd-HHMMSS>-<n>.mkv` segments of
  about 2 s, cut at keyframes, each with a `.times` sidecar listing every frame's `pts` and its time
  in milliseconds. The segment being written is `current.mkv` / `current.times` and is renamed when
  closed.
- **Rationale**: a closed segment is a complete file, so the window never reads a file that is being
  written, and a crash loses at most the open segment (principle VI). Two seconds keep the newest
  frame viewable within the spec's 2 s for cameras with a short keyframe interval. The sidecar gives
  each frame its own time, whatever the frame rate or a reconnect does.
- **Alternatives**: one growing file (rejected: Matroska writes its index at the end, a crash leaves
  it unseekable, and reading a file being written is fragile); MPEG-TS (rejected: once segments are
  short and closed it gains nothing, while Matroska holds every codec used here with an index for
  seeking); HLS-style playlists (rejected: the sidecar already is the index).
- **Known limit**: a stream whose keyframes are farther apart than 2 s makes segments as long as
  its keyframe interval, and the newest frames wait that long.

## 3. Encoding

- **Decision**: network streams (RTSP, RTMP: H.264 from the cameras) are remuxed without
  re-encoding. USB cameras and the test camera are encoded with FFmpeg's native `mpeg4` encoder,
  keyframe every 15 frames, quality scale 3.
- **Rationale**: remuxing costs no CPU and loses nothing; `mpeg4` exists in every wheel, is LGPL,
  fast, and about 2 GB an hour at 720p30 -- a 12-hour race fits a laptop disk, MJPEG would not
  (about 8 GB an hour).

## 4. Frame times

- **Decision**: a steady clock anchored to the wall clock when the recorder starts:
  `wall = anchor_wall + (monotonic - anchor_monotonic)`. A USB or test frame takes the time it was
  captured; a network frame takes the anchor of its first packet plus its `pts` distance from it,
  re-anchored when the `pts` jumps back or by more than 5 s.
- **Rationale**: frame times never move when the computer's clock is adjusted (spec edge case);
  network jitter does not shake the timeline; the remaining constant delay of a network camera is
  what the alignment of Story 7 absorbs.

## 5. The recorder outlives the window

- **Decision**: one recorder process per camera, started detached (`start_new_session` on POSIX,
  `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` on Windows) as `<photofinish> --recorder <camera>`.
  It writes `recorder.json` in its folder every second (pid, state, last error, segments, free
  disk) and stops when `stop.request` appears there. The window attaches to a recorder whose
  heartbeat is fresh, starts one otherwise, and restarts a dead one after 1 s doubling to 30 s.
  Camera reconnects happen inside the recorder with the same backoff.
- **Rationale**: principle VI; files instead of pipes mean a window started again finds a running
  recorder and never starts a second one on the same camera.
- **Alternatives**: `QProcess` children (rejected: they die with the window); a recorder thread in
  the window (rejected: a crash of the window takes the recording with it).

## 6. Viewing

- **Decision**: the window keeps, per camera, an index of closed segments and their frame times
  (numpy arrays, appended as segments close, polled every 500 ms). A decode worker thread opens the
  segment holding the wanted frame, seeks to the keyframe before it, decodes forward and hands a
  `QImage` to the view; the newest request wins.
- **Rationale**: seeking within a 2 s segment decodes at most 14 frames for `mpeg4` and one GOP for
  H.264; the interface thread never decodes.

## 7. Input and output lists

- **Decision**: the input file is polled every 500 ms (size and modification time) and, when it
  changed, opened, read whole and closed at once -- never held open, because on Windows an open
  handle without delete sharing makes the chronometer's atomic rewrite fail -- and read as complete
  lines (UTF-8, then cp1251, then Latin-1).
 `difflib.SequenceMatcher` aligns it with the input as last taken:
  inserted lines are appended to the output, replaced lines become highlighted changes, deleted
  lines mark their output lines "removed from input". The output file holds its lines in time order
  and is replaced atomically on every change; `<output>.state.json` keeps each line's origin and
  marks; `<output>.journal.txt` gets one JSON object per change.
- **Rationale**: FR-009 and FR-011; the output file stays a plain finish file that
  FinishProtocolGenerator reads, while the state and the journal carry what it cannot.
- **An output file chosen with lines in it** and no `state.json`: its lines become the output list
  with origin "outside", journaled once; the first alignment counts an input line as taken when its
  exact text is among them, so choosing last session's output again does not double it.

## 8. Sub-frame times

- **Decision**: the finish line is a segment between two points per camera, in image coordinates
  normalised to 0-1. With a point clicked on frame `a` (time `ta`) and on frame `b` (`tb`), signed
  distances `da`, `db` to the line: if they have opposite signs (or one is zero),
  `t = ta + da / (da - db) * (tb - ta)`; otherwise nothing is offered. On the timeline, a click
  between two frames when one frame interval spans at least 100 pixels gives that time.
- **Rationale**: the caliper reading the maintainer described (decision 9 of 2026-10-28) is exactly
  this linear interpolation; refusing to extrapolate keeps a mistaken click from inventing a time.

## 9. Time format

- **Decision**: times are written as the desktop chronometer writes them: `D H:M:S.mmm`, days since
  1970-01-01 in local standard time, plus one hour when the summer-time option is on during daylight
  saving.
- **Rationale**: FinishProtocolGenerator reads the output unchanged; offsets absorb any other
  difference.
