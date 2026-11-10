# Implementation Plan: PhotoFinish Camera

**Spec**: [spec.md](spec.md) | **Contract**: [contracts/phone-stream.md](contracts/phone-stream.md)

## Shape

```
android/                         the app, a Gradle project of its own
  app/src/main/java/com/dchernykh/photofinish/camera/
    stream/   Amf0, RtmpChunks, RtmpPublisher, Avc (FLV tags, Annex B), Sei
    sync/     ClockSync: the exchange and the offset it keeps
    capture/  FormatChoice (sizes, frame rates, bitrate), CameraStreamer (Camera2 -> MediaCodec)
    pairing/  the address from a QR code or typed
    MainActivity + ui/: Compose screen, settings kept in SharedPreferences
app/recorder/clock_sync.py       the recorder's answer to the exchange
app/recorder/frame_time.py       the frame moment read from a packet's SEI
```

- **No streaming library.** The moment must ride inside each frame, which needs the H.264 units in
  hand before they are packed for RTMP; the RTMP publisher PhotoFinish needs (FFmpeg's listener
  as the server) is a few hundred lines, unit-tested against a fake server.
- **Camera2 straight into the encoder's input surface**, so the encoder's presentation times are
  the camera's sensor timestamps; the app works out which of its clocks they follow
  (`SENSOR_INFO_TIMESTAMP_SOURCE`, else by comparing at the first capture).
- **Toolchain as ChronometerAndroid's**: AGP 8.13.2, Kotlin 2.2.21, Gradle 8.14.5, compileSdk 36,
  Compose BOM 2025.07.00; ktlint, detekt, Android lint, unit tests, Kover.
- **Release** as ChronometerAndroid's: the release run builds the APK signed from repository
  secrets and attaches `photofinish-camera-<version>.apk` to PhotoFinish's release.

## Tests

- JVM unit tests for everything under `stream/`, `sync/`, `pairing/` and the choice of settings;
  Kover gates them.
- PhotoFinish: the SEI reader and the clock answer are Qt-free and unit-tested; an RTMP stream
  carrying moments, pushed by PyAV, is recorded at those moments.
- By hand, in tandem: the app on the `Xiaomi_17_Ultra` emulator streams to a recorder on the same
  computer; then on the Xiaomi 17 Ultra itself.
