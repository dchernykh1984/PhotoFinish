# Quickstart: the live editor with the test camera

1. `uv run python -m app.main`.
2. Cameras -> Add...: Connection "Test camera", 60 frames a second, scene "bar". Recording
   starts; the picture shows a clock and a bar whose front crosses the centre line at .500 of
   every second.
3. Input file...: a chronometer's results file (any `number#time#action#` file). Output file...:
   a new file, e.g. `results_video.txt`. The output list fills with the input lines.
4. Step with Left/Right (one frame), Shift+Left/Right (ten), Ctrl+Left/Right (one second), L for
   Live. Type a number, Enter: a crossing at the frame shown.
5. Caliper: type a number (or choose an output line), click the bar's front on the frame before
   the centre line and on the frame after it; accept the time offered.
6. Kill the window (not the recorder): start it again; recording went on, and the output and
   journal hold every change.
7. A second camera: add another test camera with the scene "flash"; "Mark event" on the flash on
   each camera, and both show the same moment.
8. Real cameras: presets "SJCAM HD1080P over USB", "SJCAM HD1080P over its Wi-Fi" (join the
   camera's Wi-Fi first) and "SJCAM SJ10 Pro over RTMP" (type the address the camera dialog and
   the camera list show into the SJCAM app's live stream settings). All three say "untested"
   until tried with the real cameras.
