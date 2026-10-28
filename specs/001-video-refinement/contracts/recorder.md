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
A heartbeat older than 5 s means the recorder is gone.

## Control

- `stop.request` appears: the recorder closes the open segment and exits with state `stopped`.
- Starting is the window's job: it starts a recorder only when no fresh heartbeat exists.

## Output

- Segments and `.times` files as `data-model.md` describes; a segment is renamed from `current.*`
  only after both files are flushed and closed.
- `gaps.txt` gets a line for every stretch without frames longer than three frame intervals.
- Below 2 GB free the state stays `recording` with `detail` "low disk"; on a failed write for lack
  of space the state becomes `disk_full` and the recorder exits.
