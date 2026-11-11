# Implementation Plan: Several lenses of one phone, and one camera large

**Spec**: [spec.md](spec.md) | **Contract**: [../003-phone-camera-app/contracts/phone-stream.md](../003-phone-camera-app/contracts/phone-stream.md)

## Shape

```
app/cameras.py                    LENSES, pairing_text: the QR code's text
app/widgets/camera_dialog.py      the lens checkboxes; cameras(): one camera per lens
app/main_window.py                adds every camera the dialog makes; One camera, Ctrl+N/0/Up/Down
app/widgets/number_field.py       passes Up and Down on, for Ctrl+Up and Ctrl+Down
android/.../pairing/Pairing.kt    Lens, LensTarget, the code's text read
android/.../capture/Lenses.kt     LensInfo, LensChoice (classify), SessionPlan (devices to open)
android/.../capture/PhoneLenses.kt  the phone's cameras read through Camera2 (glue)
android/.../capture/CameraStreamer.kt  a stream per lens: encoder, uplink, clock exchange
android/.../ui/                   a status line per lens, the lenses found
```

- **The recorder is untouched.** A lens is a camera of its own to PhotoFinish: a port, a recorder,
  a folder; the clock exchange runs per lens, so each stream's moments are on its own recorder's
  clock.
- **One capture session per camera device.** The lenses of a logical camera are its physical
  cameras, each output given its physical id (Android 9); Android 10 and later are asked
  beforehand whether the outputs are supported (`isSessionConfigurationSupported`), and the app
  falls back: the preview on the first lens, then the preview of the camera, then no preview, then
  fewer lenses. Android 8 streams one lens, as before.
- **A second camera device** -- the front with the back -- only when `concurrentCameraIds`
  (Android 11) lists the pair; trying an unlisted pair may cut the first camera, which would then
  be opened again and again.
- **Debug only, for the emulator**: `--es facing front` takes the lenses from the front camera and
  gives the back camera the role of "front", as the emulator's front camera is the logical one of
  two lenses (`hw.camera.front=emulated`).

## Tests

- JVM: `Pairing.parse` (both forms, unreadable lines, duplicates), `LensChoice.classify` (logical
  and plain cameras, thresholds), `SessionPlan.plan` (grouping, physical ids, missing lenses,
  cameras that cannot run together); Kover gates them.
- Python: `cameras.pairing_text`; the dialog's cameras for one and several lenses (ids, ports,
  paths, names, code); the window: One camera, Ctrl+N, Ctrl+0, Ctrl+Up/Down, hidden cameras not
  decoded, the moment kept.
- By hand, in tandem: the emulator's two front lenses and its back camera to three recorders; then
  the Xiaomi 17 Ultra.
