---
name: trying-a-camera
description: Connecting a real camera to PhotoFinish and judging its video - the phone with PhotoFinish Camera or a streaming app, the numbers that tell a usable stream from a bad one, probing a camera's own Wi-Fi, and what the action cameras taught. Use when the maintainer debugs a camera, a stream looks bad, or a new phone, app or camera is tried.
---

# Trying a camera

## The camera is a phone

A phone on a tripod runs PhotoFinish Camera, our own app (`android/`, the
`android-app` skill), or a free streaming app; either pushes RTMP to PhotoFinish.

- **PhotoFinish Camera.** The add-camera dialog shows a QR code the app scans.
  Each frame carries its moment on the recorder's clock, so the recording's
  steps follow the camera, not the Wi-Fi. Tried on the emulator; the Xiaomi 17
  Ultra, then the Xiaomi 11 Ultra, are the phones to make it work on first.
  Install the APK from the release, or a debug build with `adb install`.
- **Streaming apps.** Larix Broadcaster was tried: a Xiaomi 17 Ultra gave 2560x1440 at
  59.9 fps; its free version writes "TEST STREAM" over the picture. IP Camera by
  ShenYao is free with ads and still to be tried. PRISM dropped 60 fps on
  Android.
- **Adding it.** Cameras -> Add... offers "Phone streaming app, sending here
  (RTMP)" first and shows the address to type in the app.
- **Settings.** 60 fps (the app's list shows what the phone gives third-party
  apps; many Androids give 30 only), 1080p or 1440p, about 10 Mbit/s (Larix
  multiplies the bitrate set by 1.6 at 50 fps and more), a keyframe a second:
  PhotoFinish cuts segments at keyframes, so the newest frame waits that long.
- **Network.** The computer on the phone's own hotspot keeps the phone's mobile
  internet, so a remote or agent session stays up; one shared Wi-Fi works too.

## A phone's other lenses

Tick them in the add-camera dialog (Ultra-wide, Telephoto, Front): each is a
camera of its own, and PhotoFinish Camera streams them all from the one code.
The app lists, under its controls, the lenses the phone gives apps, with their
35 mm-equivalent focal lengths; a lens missing there the phone hides from apps
(Xiaomi has), and one it cannot stream with the others is said on its line. Each
lens costs its bitrate on the Wi-Fi -- about 10 Mbit/s at 1080p60 -- and heat:
several lenses for hours want shade and a charger.

## What the phone says of itself

Under the recording banner, a line per phone running PhotoFinish Camera: battery
(with a charging mark), the battery's temperature, a fire mark once Android's
thermal state is moderate or worse, the Wi-Fi signal (none when the phone is the
hotspot), power saver, frames dropped for the network in the last minute. Amber:
25 % or less not charging, 40 degrees C, moderate, -70 dBm, saver on, any frame
dropped. Red: 10 % or less not charging, 45 degrees C, severe, -80 dBm. Greyed
with a time: the phone has not been heard for 5 s -- its last word. The readings
ride the keyframes (`PFS1` SEI), so they come only while the video does; try
them on the emulator with `adb emu power capacity 9` and `adb emu power ac off`.

## Measuring a recording

Numbers, not impressions. Run against the camera's folder next to the program:

```python
import os, sys, av

folder = sys.argv[1]  # .../video/<camera id>
os.chdir(folder)
names = [n.strip() for n in open("segments.txt") if n.strip()]
bases = [n.removesuffix(".mkv") for n in names]
moments, size = [], 0
for b in bases:
    size += os.path.getsize(b + ".mkv")
    moments += [int(l.split()[1]) for l in open(b + ".times") if len(l.split()) > 1]
span = (moments[-1] - moments[0]) / 1000
gaps = [(b - a) / 1000 for a, b in zip(moments, moments[1:]) if b - a > 50]
print(f"{len(moments)} frames, {span:.1f} s, {len(moments) / span:.1f} fps")
print(f"{size * 8 / span / 1e6:.1f} Mbit/s; {len(gaps)} gaps, {sum(gaps):.1f} s")
with av.open(bases[-2] + ".mkv") as video:
    frame = next(video.decode(video=0))
    print(frame.width, frame.height)  # frame.to_ndarray() for a look at it
```

A usable stream: the frame rate set, gaps under a percent of the time, the
bitrate set. From PhotoFinish Camera, also every frame with its own moment and
steps within a millisecond or two of the frame interval: the `android-app`
skill reads them. The SJCAM SJ10 Pro over its Wi-Fi gave 23 of 30 fps, 49 s without
frames in 204 s and 0.9 Mbit/s: unusable for timing.

## Probing a camera's own Wi-Fi

Joining a camera's access point takes the computer off the internet, and a
remote or agent session stops until it is back. Prepare everything first:

- Start a probe in the background that waits for the Wi-Fi address (`ipconfig
  getifaddr en0`) to change, scans the gateway's ports (80, 554, 7878, 8192),
  tries RTSP paths (`live`, `xxx.mov`, `sjcam.mov`), and, on an Ambarella camera
  whose plain RTSP fails, opens a session on port 7878 (`msg_id` 257, then 259
  with `none_force`).
- Hand the result over while offline: copy the URL found with `pbcopy`, show it
  with `osascript` `display dialog`, and exit only once the address changes back.
- The SJ10 Pro is Ambarella: `rtsp://192.168.42.1:554/live` over TCP plays with
  no session, and it is the phone preview only. Its menu offers no way to join
  another network, so RTMP push needs the SJCAM app, if it works at all.

## Cables and macOS

- `system_profiler SPUSBHostDataType SPCameraDataType` lists what is plugged in.
  Nothing new listed means no data over the cable: a charge-only cable, an
  accessory macOS has not allowed, or a device that offers no video. The SJ10
  Pro offered none.
- A release build opens a USB camera only because `build.yml` writes
  `NSCameraUsageDescription` into the bundle; without it TCC kills the recorder
  at once. Run from source, the terminal's or editor's own declaration hides
  that, and PR builds run on Linux: only a release shows it.
