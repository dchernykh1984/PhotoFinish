# Data model: live finish video and the referee's list of crossings

## Event folder (next to the program, `app/paths.py`)

```text
data/session.json                  the session (below)
video/<camera id>/
  recorder.json                    the recorder's heartbeat and state
  recorder.lock                    held locked while a recorder runs
  stop.request                     present while the window asks the recorder to stop
  <YYYYmmdd-HHMMSS>-<n>.mkv        a closed segment
  <YYYYmmdd-HHMMSS>-<n>.times      its frames: "<pts> <time ms>" per line
  current.mkv, current.times       the segment being written
  segments.txt                     the closed segments' names, one a line, as they closed
  crashed-<ms>.mkv, .times         a segment a crash left open, kept but not shown
  gaps.txt                         "<from ms> <to ms> <reason>" per gap
<output file>                      chosen by the referee
<output file>.state.json           origin and marks of each output line, the input as last taken
<output file>.journal.txt          one JSON object per change
<output file>.outside-<stamp>      a version of the output something else wrote, kept
<output file>.state.json.broken-<stamp>  a state that could not be read, kept
```

## Camera

| Field | Meaning |
| --- | --- |
| `id` | folder name, `cam1`, `cam2`... |
| `name` | shown to the referee |
| `connection` | `usb`, `rtsp`, `rtmp`, `test`, `file` |
| `settings` | per connection: `device`, `width`, `height`, `fps` (`usb`); `url`, `transport` `tcp` or `udp` (`rtsp`); `port`, `path` (`rtmp`); `fps`, `width`, `height`, `scene` (`test`); `path` (`file`) |
| `preset` | `sjcam-hd1080p-usb`, `sjcam-hd1080p-wifi`, `sjcam-sj10pro-rtmp` or none |
| `finish_line` | `[[x1, y1], [x2, y2]]`, 0-1 image coordinates; default the vertical centre line |
| `offset_ms` | added to this camera's frame times to put it on the first camera's timeline |
| `record` | false for a file opened after the race |
| `zone` | `[[x1, y1], [x2, y2]]`, two corners in 0-1 coordinates where riders are looked for (specification 002); default a band around the finish line |

## Frame

`camera`, `segment`, `pts`, `ms` (time on the camera's clock), `video_ms = ms + offset_ms`.

## Input line (in memory)

`text` (the line without its line break) and, when the chronometer changed it since it was taken,
`taken`: the content taken, which the output keeps until the referee copies the change. A line
gone from the input is marked on its output line (`removed_from_input`).

## Output line

| Field | Meaning |
| --- | --- |
| `text` | `number#time#action#`, as written to the output file |
| `origin` | `{"input": <the input text taken>}`, `{"added": true}`, or `{"outside": true}` for a line found in the file when it was chosen |
| `method` | `input`, `frame`, `interpolated`, `hand`, `typed`; `outside` for a line found in the file |
| `removed_from_input` | the input line it came from is gone |

The output file is the `text` of every line, sorted by time, stable; lines without a readable time
follow, in the order they were taken. Every change writes the state first, then the output file,
then its journal entries: after a crash between the two files, the state is ahead and writes the
file again at the next start. A change that cannot be written writes the state back as it was and
leaves nothing in the journal.

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
  "analysis": {"on": false, "model": ""}
}
```

## Output state (`<output file>.state.json`)

```json
{
  "version": 1,
  "lines": [{"text": "15#20389 11:35:29.594#nextLap#",
             "origin": {"input": "15#20389 11:35:29.615#nextLap#"},
             "method": "frame", "removed_from_input": false, "encoding": "utf-8"}],
  "input_taken": ["15#20389 11:35:29.615#nextLap#"],
  "removed_input": []
}
```

`removed_input` holds the input lines whose crossing the referee removed: such a line is not
taken again when it leaves the input and comes back.
