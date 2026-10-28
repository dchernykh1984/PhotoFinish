# Quickstart: the live editor with the test camera

1. `uv run python -m app.main`.
2. Cameras -> Add -> "Test camera" (60 fps, scene "finish"). Recording starts; the picture shows a
   clock and a bar crossing the centre line every few seconds.
3. Input: choose a chronometer's results file (any `number#time#action#` file). Output: choose a new
   file, e.g. `results_video.txt`. The output list fills with the input lines.
4. Step with Left/Right (one frame), Shift+Left/Right (ten), Ctrl+Left/Right (one second), L for
   Live. Type a number, Enter: a crossing at the current frame.
5. Caliper: click the bar's front on the frame before the line and on the frame after it; accept
   the offered time.
6. Kill the window (not the recorder): start it again; recording went on, and the output and
   journal hold every change.
7. Real cameras: presets "SJCAM HD1080P (USB)", "SJCAM HD1080P (Wi-Fi)" (join the camera's Wi-Fi
   first) and "SJCAM SJ10 Pro (RTMP)" (type the address PhotoFinish shows into the SJCAM app's live
   stream settings). All three are marked untested until tried with the real cameras.
