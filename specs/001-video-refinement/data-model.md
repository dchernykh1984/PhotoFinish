# Data model: live finish video and the referee's list of crossings

## Event folder (next to the program, `app/paths.py`)

```text
data/session.json                  the session (below)
video/<camera id>/
  recorder.json                    the recorder's heartbeat and state
  stop.request                     present while the window asks the recorder to stop
  <YYYYmmdd-HHMMSS>-<n>.mkv        a closed segment
  <YYYYmmdd-HHMMSS>-<n>.times      its frames: "<pts> <time ms>" per line
  current.mkv, current.times       the segment being written
  gaps.txt                         "<from ms> <to ms> <reason>" per gap
<output file>                      chosen by the referee
<output file>.state.json           origin and marks of each output line
<output file>.journal.txt          one JSON object per change
```

## Camera

| Field | Meaning |
| --- | --- |
| `id` | folder name, `cam1`, `cam2`... |
| `name` | shown to the referee |
| `connection` | `usb`, `rtsp`, `rtmp`, `test`, `file` |
| `settings` | per connection: device name, size and rate (`usb`); `url` (`rtsp`); `port`, `path` (`rtmp`); `fps`, `scene` (`test`); `path` (`file`) |
| `preset` | `sjcam-hd1080p-usb`, `sjcam-hd1080p-wifi`, `sjcam-sj10pro-rtmp` or none |
| `finish_line` | `[[x1, y1], [x2, y2]]`, 0-1 image coordinates; default the vertical centre line |
| `offset_ms` | added to this camera's frame times to put it on the first camera's timeline |
| `record` | false for a file opened after the race |

## Frame

`camera`, `segment`, `pts`, `ms` (time on the camera's clock), `video_ms = ms + offset_ms`.

## Input line (in memory)

`index` in the input file, `text` (the line without its line break), `ms` (its time), state:
`taken`, `changed` (with the content taken and the current content), `removed`.

## Output line

| Field | Meaning |
| --- | --- |
| `text` | `number#time#action#`, as written to the output file |
| `origin` | `{"input": <the input text taken>}` or `{"added": true}` |
| `method` | `input`, `frame`, `interpolated`, `hand`, `typed` |
| `removed_from_input` | the input line it came from is gone |

The output file is the `text` of every line, sorted by time, stable.

## Session (`data/session.json`)

```json
{
  "version": 1,
  "input": "path as chosen",
  "output": "path as chosen",
  "summer_time": false,
  "finish_mode": false,
  "source_offset_ms": 0,
  "cameras": [{"id": "cam1", "name": "Side", "connection": "test", "settings": {}, "preset": null,
               "finish_line": [[0.5, 0.0], [0.5, 1.0]], "offset_ms": 0, "record": true}],
  "input_taken": ["15#20389 11:35:29.615#nextLap#"],
  "input_changes": [{"taken": "...", "current": "..."}]
}
```
