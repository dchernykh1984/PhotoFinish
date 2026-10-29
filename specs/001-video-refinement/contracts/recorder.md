# Contract: a camera's recorder

The recorder is `<photofinish> --recorder <camera id>` (in development
`python -m app.main --recorder <camera id>`). It reads the camera's settings from
`data/session.json`, records into `video/<camera id>/` and is controlled through files there, so
it keeps recording when the window is gone.

## `recorder.json`, rewritten every second

```json
{"pid": 4242, "heartbeat_ms": 1761716129000, "state": "recording", "detail": "",
 "frames": 123456, "segments": 412, "free_bytes": 52345678901, "connection": "test"}
```

`state`: `starting`, `connecting`, `recording`, `reconnecting`, `stopped`, `disk_full`, `failed`.
A heartbeat older than 15 s means the recorder is gone: a camera open blocks up to 10 s without
one. While an RTMP camera has not called in, the state is `connecting` with `detail` "waiting for
rtmp://<this computer>:<port>/<path>", the address to type in the camera app.

## Control

- `stop.request` appears: the recorder closes the open segment, exits with state `stopped` and
  removes the request.
- Starting is the window's job: it starts a recorder only when no fresh heartbeat exists.
- `recorder.lock` is held locked while a recorder runs: a second recorder for the same camera
  exits at once and leaves the first one's heartbeat alone.
- Exit codes: 0 stopped on request, 2 the camera is not in the session or its settings cannot work
  (state `failed`), 3 another recorder has the camera, 4 the disk is full (state `disk_full`).

## Output

- Segments and `.times` files as `data-model.md` describes; a segment is renamed from `current.*`
  only after both files are flushed and closed, the `.times` first, and its name is then appended
  to `segments.txt`, the list readers follow instead of the folder. A recorder that starts lists
  any closed segment a crash left out. A `current.*` a crash left is
  kept as `crashed-<ms>.*` when the next recorder starts and is not shown.
- `gaps.txt` gets a line for every stretch without frames longer than three frame intervals.
- Below 2 GB free the state stays `recording` with `detail` "low disk"; on a failed write for lack
  of space the state becomes `disk_full` and the recorder exits.
