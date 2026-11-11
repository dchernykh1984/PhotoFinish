# Implementation Plan: What may stop a phone's stream, shown on the laptop

**Spec**: [spec.md](spec.md) | **Contract**: [../003-phone-camera-app/contracts/phone-stream.md](../003-phone-camera-app/contracts/phone-stream.md)

## Shape

```
android/.../status/PhoneStatus.kt        the readings, and the line they are written as
android/.../status/PhoneStatusReader.kt  the readings from Android (glue)
android/.../stream/Sei.kt                phoneStatus: the SEI holding the line
android/.../stream/Uplink.kt             the status SEI on each keyframe, with its dropped frames
app/recorder/frame_time.py               phone_status: the line read from a packet
app/recorder/sources.py                  Stream.phone: the last status, with when it came
app/recorder/__init__.py                 the heartbeat's "phone"
app/phone_status.py                      the readings with their levels (Qt-free)
app/main_window.py                       the line per camera under the banner
```

- **In the video, not beside it.** The status rides the frames, as their moments do: no channel
  of its own, nothing new to open on the laptop, and it reaches the recorder exactly while the
  video does. Under PhotoFinish's UUID with its own mark, `PFS1`, after the moment's SEI: a reader
  that looks for `PFT1` passes over it.
- **A line of `key=value` pairs**, so a reading can be added without changing the format.
- **Once a second**, on keyframes: the readings change slowly; Android's battery broadcast and
  power manager are asked then, on the uplink's thread.

## Tests

- JVM: the line (`PhoneStatus.line`), the SEI (sizes past 255, escaping), the uplink putting it on
  keyframes only and after the moment.
- pytest: `frame_time.phone_status`; the stream keeping the last status; the heartbeat; the
  levels (`phone_status.readings`); the window's line, its colours, names escaped, greyed when old.
- By hand: the emulator in tandem, its battery set with `adb emu power`.
