# Implementation Plan: Nothing the phone kept is lost

**Spec**: [spec.md](spec.md) | **Contract**: [../003-phone-camera-app/contracts/phone-stream.md](../003-phone-camera-app/contracts/phone-stream.md)

## Shape

```
android/.../stream/FrameStore.kt     each run's index written beside its frames, synced at keyframes;
                                     read back at a start; held by the wall clock for frames read back
android/.../stream/KeptStore.kt      a kept stream's folder: what it needs to be sent (address, format,
                                     codec, header), written once known, read back
android/.../stream/Uplink.kt         a stream of kept frames alone (no camera, no clock); waits for its
                                     turn at an address and for the first lens; says what it holds
android/.../capture/Backlog.kt       the streams kept with no encoder: read back at the start, handed
                                     over at Stop and the like, sent one an address, oldest first
android/.../capture/Priority.kt      the first lens first: who may send now
android/.../capture/LensStream.kt    stop keeps what is unsent (handed to the backlog); discard drops it
android/.../capture/CameraStreamer.kt each stream a folder of its own; Stop, another choice, release
                                     hand the streams over; Discard (glue)
android/.../SendingService.kt        the foreground service and its notification (glue)
android/.../status/PhoneStatus*.kt   free storage; unsent_ms and unsent_mb
android/.../ui/*                     what is unsent, Discard and its confirmation
app/phone_status.py                  free storage: amber under 30 GB, red under 10 GB
app/catch_up.py                      a camera's video on the phone: the bar and the estimate
app/recorder/launcher.py, main_window.py  the line and its bar
```

- **One folder a stream, not a lens.** A stream's folder is named after its lens and when it began,
  so a stream sent after a restart and the new one of the same lens never share files. Its header
  file (`stream.txt`) holds what sending needs; a folder without one, or without a run with a
  moment, is removed at the start.
- **The index on disk.** Each run's frames are in `<n>.h264` as now; `<n>.idx` gets a 33-byte
  record a frame, written after the frame's bytes: size, capture time, moment (none as
  Long.MIN_VALUE), keyframe, wall-clock ms. Reading back stops at the first record whose bytes are
  not all there, or that is cut short: a crash mid-write loses that frame alone. At each keyframe
  the run before is synced (`FileDescriptor.sync`): a power cut costs at most a second.
- **Sent from the backlog.** A stream kept with no encoder -- read back at the start, or handed
  over at Stop, another choice, the app closing, its encoder dead -- is a store and an uplink with
  no clock: its frames carry their moments already, frames without one are skipped to the first
  keyframe with one. The backlog sends one stream an address at a time, the oldest first, and a
  live stream waits for the address to be free before it connects: the recorder gets each camera's
  frames in the order taken. A stream sent whole -- nothing unsent 5 s -- is removed.
- **Held by the wall clock.** A frame read back may have been kept across a phone restart, its
  capture clock started again: `held_ms` is then the wall clock now less the wall clock when kept.
- **The first lens first.** Each uplink tells the priority board whether it is connected and how
  far behind it is; a lens not first sends only while the first is not connected or within 2 s,
  and closes its connection after 2 s of waiting, so it holds none meanwhile.
- **Room.** The store's cap is gone: every store keeps the phone's free space above 10 GB, the
  oldest runs of the writing stream giving way.
- **The service** runs while a lens streams or the backlog holds anything, started from the
  screen; its notification says what is left; Android 15's time-out stops it, and the store stays.

## Tests

FrameStore read back, torn records, sync points, wall-clock hold; KeptStore round trip; Backlog
order, one an address, removal once sent, discard; Priority; Uplink of kept frames alone, its turn
and its wait for the first lens; PhoneStatus keys; the laptop's readings, the bar and the estimate,
the line. On the emulator: the app killed with frames kept, then started; Stop with frames kept;
two lenses with the recorder of the first slowed.
