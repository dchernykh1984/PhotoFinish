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
one. A recorder whose process the window started and saw end is gone at once, unless it ended
with exit code 3: then the other recorder's heartbeat tells.
While an RTMP camera has not called in, the state is `connecting` with `detail` "waiting for
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
  to `segments.txt`, the list readers follow instead of the folder. The name goes to
  `closing.name` before the two renames, so a close cut between them is finished by it; a video
  refused that name again waits for it, never kept aside apart from its times. A recorder that starts lists
  any closed segment a crash left out. The open segment's `.times` gets a line as each frame is
  written and its video is flushed in clusters of at most 0.1 s, so a crash leaves what came before
  on disk. When the next recorder starts, the frames of a `current.*` a crash left whole, with
  their times, become a closed segment like any other, listed after the ones before. The
  `current.*` itself is kept as `crashed-<ms>.*`, as it was, and not shown; the stamp goes to
  `crashed.name` before the two renames, when there are two, so a video cut from its times joins its own. The copy is made as
  `recovered.mkv` and `recovered.times`, then the name it is to take goes to `recovered.name`,
  and only then is the crash kept aside and the copy named: a start that finds them finishes
  the recovery as `recovered.name` says, or, with no name written yet, drops them and recovers
  the crash again. `recovered.name` also holds the time on the first line of its source's `.times`, so a
  later crash's `current.*` is recovered in its turn, not kept aside with it.
  A recovery not yet named is named before the next is made, and listed as it is, during a run
  too, never written over; while it cannot be, a crash seen to is kept aside whole.
  `reading.crash` is there while a crash is read: a start that finds it keeps that crash aside
  unread, so a file that brought a recorder down as it was read does not bring down the next.
- `gaps.txt` gets a line for every stretch without frames longer than three frame intervals.
- Below 2 GB free the state stays `recording` with `detail` "low disk"; on a failed write for lack
  of space the state becomes `disk_full` and the recorder exits.
