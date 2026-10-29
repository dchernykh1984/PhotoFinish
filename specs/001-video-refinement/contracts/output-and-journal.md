# Contract: the output file and its journal

## Output file

- One crossing per line, `number#time#action#`, `\n` line ends, UTF-8, in time order.
- A line taken from the input keeps its bytes until the referee changes it.
- A time PhotoFinish sets is `D H:M:S.mmm` in local standard time (plus an hour with the summer-time
  option during daylight saving), hours, minutes and seconds without zero padding.
- FinishProtocolGeneratorPython reads it as a finish file; nothing else is in it.
- Replaced in one step (temporary file, flush, fsync, rename); a reader sees the old or the new
  file, never a mix.

## Journal (`<output file>.journal.txt`)

Append only, one JSON object per line:

| Key | Meaning |
| --- | --- |
| `at` | wall-clock time of the change, ISO 8601 |
| `op` | `take`, `add`, `time`, `number`, `remove`, `copy`, `outside_change` |
| `before`, `after` | the output line before and after (absent when there is none) |
| `input` | the input line it came from, when there is one |
| `camera` | camera id, when a frame was used |
| `frames` | `[[segment, pts, ms], ...]`: the frames used |
| `method` | `input`, `frame`, `interpolated`, `hand`, `typed` |
| `fraction` | for `interpolated`: where between the two frames |
| `offsets` | `{"camera_ms": ..., "source_ms": ...}` in use |
| `backup` | for `outside_change`: where the outside version was kept |
| `model` | for a crossing accepted from a suggestion (specification 002): the model that suggested it |

Example:

```json
{"at": "2026-10-29T11:35:40+05:00", "op": "time", "before": "15#20389 11:35:29.615#nextLap#", "after": "15#20389 11:35:29.594#nextLap#", "input": "15#20389 11:35:29.615#nextLap#", "camera": "cam1", "frames": [["20261029-113528-0412.mkv", 54321, 1761716129587], ["20261029-113528-0412.mkv", 54322, 1761716129604]], "method": "interpolated", "fraction": 0.41, "offsets": {"camera_ms": 0, "source_ms": -12}}
```
