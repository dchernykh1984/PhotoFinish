# Quickstart: the live editor with the test camera

1. `uv run python -m app.main`.
2. Cameras -> Add...: Connection "Test camera", 60 frames a second, scene "bar". Recording
   starts; the picture shows a clock and a bar whose front crosses the centre line at .500 of
   every second.
3. Input file...: a chronometer's results file (any `number#time#action#` file). Output file...:
   a new file, e.g. `results_video.txt`. The output list fills with the input lines.
4. Step with Left/Right (one frame), Shift+Left/Right (ten), Ctrl+Left/Right (one second), End
   for Live (L too, when no number is being typed). Type a number, Enter: a crossing at the frame
   shown.
5. Caliper: type a number (or choose an output line), click the bar's front on the frame before
   the centre line and on the frame after it; accept the time offered.
6. Kill the window (not the recorder): start it again; recording went on, and the output and
   journal hold every change.
7. A second camera: add another test camera with the scene "flash"; "Mark event" on the flash on
   each camera, and both show the same moment.
8. A phone: put this computer on the phone's hotspot (or both on one Wi-Fi); Cameras -> Add...
   offers the phone's streaming app first: OK, and type the address shown into a streaming app on
   the phone (Larix Broadcaster, IP Camera) set to 60 fps, a keyframe a second and about
   10 Mbit/s. The camera list says "recording" once the phone sends.
