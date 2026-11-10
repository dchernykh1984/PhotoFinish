---
name: android-app
description: Building, trying and releasing PhotoFinish Camera, the phone app under android/ - the Gradle gate, a recorder and the app streaming together on the emulator or a phone, reading the moments the frames carry, and the signing key. Use when changing anything under android/, the clock exchange or the frame moments, or when a phone streams badly.
---

# PhotoFinish Camera

The phone app lives in `android/`, a Gradle build of its own laid out as
ChronometerAndroid is: the same toolchain, detekt and ktlint rules, Kover gate
and release pipeline. Its protocol is
`specs/003-phone-camera-app/contracts/phone-stream.md`; the recorder's side is
`app/recorder/clock_sync.py` and `app/recorder/frame_time.py`.

## The gate

```
export JAVA_HOME="$(/usr/libexec/java_home -v 17)" ANDROID_HOME="$HOME/Library/Android/sdk"
cd android && ./gradlew ktlintCheck detekt lintDebug testDebugUnitTest koverVerify assembleDebug assembleRelease
```

CI's `android` job runs the same. `./gradlew ktlintFormat` fixes most ktlint
findings. What detekt stops most often, and the fix that keeps the code plain:

- `ReturnCount` (3): fold guards into one `if ... else` expression.
- `LongParameterList`: a constructor with 7 parameters already fails; group
  values that travel together, make test knobs `internal var`.
- `TooManyFunctions` (11 in a class): pure helpers go to the companion.
- `NestedBlockDepth`, `ComplexCondition` (4), `CyclomaticComplexMethod` (15):
  split a long composable into small ones, a loop body into a function.

Kover gates 80% of the code it measures; the Android glue (`MainActivity`,
`ui.*`, `CameraStreamer`, `CameraFormats`, `Settings`) is left out and tried on
a device. Kotlin files are ASCII (the pre-commit hook); Russian and Kazakh live
in `res/values-ru` and `res/values-kk`.

## Trying it with a recorder

Run a recorder from a scratch folder, so the repository's `data/` is not
touched: `data/session.json` there with one camera,
`{"id": "cam1", "connection": "rtmp", "settings": {"port": 1999, "path": "live/phone"}, "record": true}`.

```
cd <scratch>/tandem && PYTHONPATH=<repo> <repo>/.venv/bin/python -m app.main --recorder cam1
touch video/cam1/stop.request    # stops it
```

Not port 1935: the maintainer's own PhotoFinish may be recording a phone there,
and the app would stream into it. Look first: `lsof -nP -i :1935`.

The emulator (AVD `Xiaomi_17_Ultra`; its back camera is emulated, 1280x720 at
30 fps only), started in the background:

```
$ANDROID_HOME/emulator/emulator -avd Xiaomi_17_Ultra -no-window -no-audio -no-boot-anim -no-snapshot-save -gpu swiftshader_indirect
adb install -r -g android/app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.dchernykh.photofinish.camera/.MainActivity --es address rtmp://10.0.2.2:1999/live/phone --ez autostart true
adb exec-out screencap -p > screen.png
```

The `address` and `autostart` extras work in debug builds only; `10.0.2.2` is
the computer as the emulator sees it. A phone: USB debugging on, `adb devices`,
the same install and start with the computer's address on the shared network
(`ipconfig getifaddr en0`).

## Reading what came

```python
import statistics, sys
from pathlib import Path
import av
from app.recorder import frame_time

folder, moments, same = Path(sys.argv[1]), [], 0
for times in sorted(folder.glob("*.times")):
    rows = dict(tuple(map(int, l.split())) for l in times.read_text().split("\n") if l)
    moments += rows.values()
    with av.open(str(times.with_suffix(".mkv"))) as c:
        s = c.streams.video[0]
        for p in c.demux(s):
            if p.pts is not None:
                same += frame_time.moment_ms(bytes(p)) == rows.get(
                    round(p.pts * s.time_base * 1000)
                )
steps = [b - a for a, b in zip(moments, moments[1:])]
print(len(moments), "frames,", same, "with their own moment")
print(
    f"step {statistics.mean(steps):.2f} +- {statistics.pstdev(steps):.2f} ms, backwards {sum(x <= 0 for x in steps)}"
)
```

Run it with `PYTHONPATH=<repo>`. Good: every frame with its own moment, steps
at the frame interval within a millisecond or two, none backwards, gaps only
where the stream stopped. Then the lag: poll the newest `.times` for a few
seconds and compare its last moment with `time.time_ns()`. A real phone's
frames arrive some tens of milliseconds after their moment. Arriving before it
means the camera stamps frames late: the emulator's camera stamps each frame a
frame's time after it took it (checked with a temporary log of
`onCaptureStarted`'s timestamp against `SystemClock.elapsedRealtimeNanos()`).

## What the tandem tests taught

- A send that throws must still clear `sendingSince` (`finally`): otherwise the
  watchdog takes the stale mark for a hanging send and cuts every connection
  that follows, and the recorder sees handshakes break off (EIO).
- After failed handshakes the recorder pauses up to 30 s before listening
  again: a reconnect test waits that long.
- RTMP packets are length-prefixed, and a length of 256 to 511 bytes begins
  like an Annex B start code: the format comes from the stream's extradata.
- The preview is a SurfaceView, which turns the camera's frames upright for
  the screen; a TextureView in the locked landscape needs a matrix.
- Adaptive icons stay in `mipmap-anydpi-v26`: AAPT does not find them in
  `mipmap-anydpi`, whatever lint suggests.

## Releasing

release-please's run calls `.github/workflows/android-release.yml`, which builds
the APK signed with four repository secrets (`KEYSTORE_BASE64`,
`KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`), checks the signature, attests
it and attaches `photofinish-camera-<version>.apk` to the release. The versionCode
is that run's number. The keystore is
`~/android-keystores/photofinish-camera-release.jks`, beside ChronometerAndroid's,
never in the repository: an APK signed with another key does not install over
the old one, so phones would have to uninstall first.
