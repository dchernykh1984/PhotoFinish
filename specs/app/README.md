# PhotoFinish as it works today

The finish referee checks the crossings a chronometer recorded against video from one or more
cameras and corrects their times. PhotoFinish reads the chronometer's results file and never
writes to it; the referee's crossings go to an output file of their own, which
FinishProtocolGeneratorPython reads as a finish file. Built by
[001-video-refinement](../001-video-refinement/spec.md).

## Files, next to the program

| File | What it holds |
| --- | --- |
| `data/session.json` | The input and output files chosen, the cameras with their settings, finish lines and offsets, the summer-time and finish-mode switches, the timing source's offset. |
| `video/<camera>/<YYYYmmdd-HHMMSS>-<n>.mkv`, `.times`, `segments.txt` | A camera's recording in one-second segments; each frame's timestamp and moment; the segments' names as they closed, the list readers follow. |
| `video/<camera>/gaps.txt` | Stretches without frames: a restart, a reconnect, a camera that stalled. |
| `video/<camera>/recorder.json`, `recorder.lock`, `recorder.log`, `stop.request` | The recorder's heartbeat, its lock, its output, the window's request to stop. |
| `<output>` | The referee's crossings, `number#time#action#`, in time order. |
| `<output>.state.json` | Where each output line came from, how its time was had, and the input as last taken. |
| `<output>.journal.txt` | One JSON object per change: what, before and after, the input line, the camera and frames, the method, the offsets; the model, for a suggestion accepted. |
| `temp/<output stem>-<place>/<stamp><suffix>` | The output as each change left it: a copy a change, as the chronometers keep theirs; `<place>` is six hex of the output's path. |
| `video/<camera>/activity.jsonl`, `analyzer.json` | Finding riders (experimental): the stretches with a rider in view, a line per segment; how far the analyser has got. |
| `video/<camera>/suggestions.jsonl`, `suggestions.done.jsonl` | Crossings a detection model suggested; those the referee accepted or dismissed. |
| `models/<model>.onnx` | A detection model, downloaded when it is chosen or found missing at start, and checked against its pinned SHA-256. |

Formats: [output and journal](../001-video-refinement/contracts/output-and-journal.md),
[recorder](../001-video-refinement/contracts/recorder.md),
[data model](../001-video-refinement/data-model.md).

## Recording

Each camera is recorded by a process of its own, the program run as
`PhotoFinish --recorder <camera>`. The window starts it, or finds it running and attaches to it;
killing the window does not stop it, and a recorder that dies is started again after 1 s, the
pause doubling to 30 s while it keeps failing. A lock keeps a second recorder off a camera.
The segment being written reaches the disk as it is written, its video every 0.1 s: the frames a
dead recorder wrote whole are shown once the next one starts, so a crash costs the time the
recorder is down and at most the 0.1 s before it.

- USB cameras, files played as live and the test camera are encoded (mpeg4, a keyframe every 15
  frames); RTSP and RTMP streams are kept as the camera encoded them, cut at its keyframes.
- A frame's moment is the computer's clock when the camera's first frame arrived plus the frame's
  own timestamp's distance from it: arrival jitter does not shake the timeline, and setting the
  computer's clock does not move frames already recorded.
- A frame from PhotoFinish Camera carries its own moment: when the phone's camera took it, on the
  recorder's clock, in an SEI the phone writes in front of the frame. The recorder of a phone
  camera answers the phone's clock exchange over UDP on the camera's port, and the phone keeps
  its camera clock in step from it (`specs/003-phone-camera-app/contracts/phone-stream.md`):
  Wi-Fi delays do not move the frame. A connection's first frame decides for all of it: a moment
  not after the frame was read and at most 5 s before it is believed; else -- no moments, or a
  phone clock out of step -- its frames are placed by their arrival, and the camera list says
  why. A port another program holds is tried again every 5 s, and said meanwhile. A phone that
  hangs up is listened for again at once. A pushed stream is looked over for half a second
  before its first frame (FFmpeg's default is five), so frames placed by their arrival are not
  seconds late.
- A segment is shown once it is closed, about a second after its first frame: the newest frame
  is on screen within 2 s of its capture for cameras with a keyframe at least every second.
- Below 2 GB free the camera list says so; a full disk stops the recorder, which keeps what it
  recorded.

## Cameras

The camera is a phone on a tripod running PhotoFinish Camera, the Android app released with
PhotoFinish (`android/`), or a free streaming app; either pushes its video here over the local
network (RTMP: PhotoFinish listens), and the phone's own hotspot or any Wi-Fi carries it. Adding a
camera offers that first and shows the address to type in the app and, as a QR code, for
PhotoFinish Camera to scan. PhotoFinish Camera streams H.264 without sound at the size and rate
chosen (60 fps first), a keyframe a second and a bitrate that follows the size, and connects again
on its own after a loss; it keeps the screen on, and can dim it while it streams. A streaming app
is set to 60 fps, about 10 Mbit/s and a keyframe a second: the newest frame waits for the next
keyframe. Tried: a Xiaomi
17 Ultra with Larix Broadcaster sent 2560x1440 at 59.9 fps, 9 Mbit/s, 0.15 s without frames in a
minute. The other connections: network stream a camera serves (RTSP, over TCP or UDP), USB camera,
test camera, video file. Action cameras were tried and dropped: the SJCAM SJ10 Pro sends only its
phone preview over its own Wi-Fi -- 1280x720, about 0.9 Mbit/s, seconds without frames -- and no
video over its cable.

A video file is either played as if filmed now (and recorded, for trying things out) or, the
usual case, opened as it is: a camera's own recording from its card, placed by the file's creation
time and aligned like any camera. The file is never written.

The test camera draws its moment as a clock (local standard time) and as a strip of blocks a test
reads back; its scenes add a bar crossing the frame once a second, a flash for 100 ms every 5 s,
or a swaying patch.

## The window

- **Video.** Every camera's view side by side, each at its frame nearest the moment shown; the
  chosen camera, framed in blue, is the one the keys step through. The timeline shows its
  recording and gaps; the wheel zooms around the pointer, a click moves there.
- **Keys** (they work while a number is typed): Left/Right one frame, Shift ten, Ctrl one second,
  End back to Live (L too, when no number is being typed: a number may hold an L). Live follows
  the newest frame.
- **Play, Pause, Stop.** Play runs the recording from the moment shown at its own speed, every
  camera following. Each frame shown is one asked for, the next asked once it is on screen, so
  a slow computer shows fewer frames, never late ones; a gap of more than a second in the
  recording is jumped over, and playing on past the newest frame is Live. Pause holds the frame shown -- Live too, while
  recording goes on -- and asks for it again, so a crossing is timed on the frame on screen;
  while playing, timing waits for Pause. Stop goes back to the frame Play started from.
- **Input.** New lines of the chronometer's file arrive in the output within 2 s, as they are. A
  line the chronometer changes is held back, highlighted with both contents, until "Copy to
  output"; a line that is gone leaves its output line marked; a line the referee removed is not
  brought back. A restart knows which lines were taken.
- **Output.** Number and Enter: a crossing at the frame shown, a finish or a lap as the Finish box
  says. On the chosen output line: Time from frame, Type time (a full `D H:M:S.mmm`), Number,
  Remove after a confirmation. Every change is written at once, journaled, and copied to `temp/`.
- **Lists follow the video:** the lines nearest the moment are marked and kept in view; picking a
  line moves the video to its time.
- **Caliper.** Click the same point of the rider -- the front of the wheel -- on a frame before the
  finish line and on one after it: the time it crossed is offered to accept or adjust, and goes to
  a crossing for the typed number or, with no number typed, to the chosen output line. Points on one side give nothing.
  "Finish line" draws a camera's line with two clicks; the default is the picture's vertical
  centre. Zoomed in until a frame interval is 100 pixels wide, a click on the timeline between two
  frames offers that moment, picked by hand.
- **Cameras in step.** "Mark event" on a moment every camera shows -- a flash, a hand wave -- on
  each camera in turn: each takes the offset that shows it at the first one's moment. Once every
  camera is aligned, or 10 minutes on, the next mark starts a new event.
- **Timing source.** "Align with source" on an input line and the frame of the same passing: from
  then on lines open at the right frame, and times set from frames are written on the
  chronometer's clock. The offset is shown beside the time and journaled with every change.
- **Outside changes.** An output file changed by something else is kept in a backup beside it,
  journaled, and written again from the referee's list.

## Finding riders (experimental, off by default)

Built by [002-video-analysis](../002-video-analysis/spec.md). Timing stays by hand; this only
helps find the moments to look at.

- **Find riders** starts an analyser process per recording camera: below the recorder in
  priority, a child of the window that ends with it. It reads closed segments only, so recording
  and timing never wait for it, and a segment it has indexed is not indexed again.
- **Without a model** a rider is motion inside the camera's **Zone** (two clicks; by default a band
  around the finish line) that travels at least a quarter of the zone across the line within
  2 s: leaves and grass swaying in place mark nothing.
- **With a model** -- a YOLOX COCO detector in ONNX (Apache-2.0), chosen in the model list:
  YOLOX-Nano, YOLOX-Tiny or YOLOX-S, each downloaded from the YOLOX releases when it is chosen,
  or at start when the one chosen is missing, checked against its pinned SHA-256 and kept in
  `models/` next to the program; or **Model file...** for one of the referee's own. The
  download's progress shows in the list; choosing anything else stops it, and a download that
  fails is said and changes nothing. While the model in use is missing no analyser starts, and
  the camera list says so -- a rider is a person or a bicycle overlapping the zone, looked for twice a second on the CPU. A
  model that cannot be used is said in the camera list and the analysis stops.
- The timeline shows the stretches with a rider in view; **Next rider** and **Previous rider**
  (PageDown, PageUp) jump between their starts; the camera list says how far each camera's
  analysis has got.
- **Suggested crossings** (with a model): a rider followed from sample to sample whose front
  changes side of the finish line is looked for again on the frames between, and the two
  around the line give the moment, as the caliper does. Pick one to see it; **Accept with the
  number** adds the crossing through the output's usual path, journaled with the model;
  **Dismiss** drops it. Neither comes back.

## Known limits

- The Linux builds cannot capture USB cameras (PyAV's Linux wheels have no video4linux2): the
  camera dialog says so, and a camera's stream or a file is used there instead.
- A network camera's timestamps follow its own clock, which can drift from the computer's by a few
  tenths of a second over a long day: align again when it shows. PhotoFinish Camera's do not: its
  clock is brought into step every 2 s.
- On a network with no gateway this computer's address is looked up by its name, which on
  some Linux systems gives only a loopback address: the camera dialog then shows no QR code,
  and the address is typed in the phone.
- PhotoFinish Camera has been tried on the Android emulator, whose camera stamps a frame a frame's
  time later than it took it; the Xiaomi 17 Ultra and the Xiaomi 11 Ultra come first among real
  phones. A phone whose camera stamps its frames on neither of Android's clocks streams them
  without their moments, placed by their arrival, and the app says so.
- A stream whose keyframes are farther apart than a second makes segments that long, and its
  newest frames wait that long.
- Finding riders: a zone drawn or a model chosen applies from then on; segments already
  indexed keep their stretches. Riders in a bunch can be taken for one another, and night, rain
  or a low sun can hide them: scroll by hand, as always.
- On Windows the portable build is one file that unpacks itself; a recorder started from it first
  waits for that: it unpacks a copy of its own (`PYINSTALLER_RESET_ENVIRONMENT`), not the window's,
  which is deleted when the window closes. Whether it leaves the window's job on every Windows
  setup is still to be seen on the maintainer's machines.
