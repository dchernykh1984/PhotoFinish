# Feature Specification: PhotoFinish Camera, the phone app

**Feature Branch**: `feat/phone-camera-app`

**Created**: 2026-11-10

**Status**: Draft

**Input**: Maintainer's decisions of 2026-11-10, after trying the cameras at hand:

- The finish camera is a phone on a tripod. Free streaming apps either write a watermark over the
  picture (Larix Broadcaster) or drop 60 fps on Android (PRISM), so PhotoFinish gets an app of its
  own, released with it, free, and depending on no one.
- First the Xiaomi 17 Ultra, then the Xiaomi Mi 11 Ultra; other phones later, as they are tried.
- What a free app cannot give: settings fixed to what a photo finish needs, pairing without typing,
  and the moment each frame was taken on the computer's clock, so a slow or jittery Wi-Fi no
  longer moves the video's time.
- PhotoFinish keeps taking RTMP from any app: an iPhone, or a phone the app does not suit.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A phone streams to PhotoFinish without typing (Priority: P1)

The referee adds a camera in PhotoFinish; the dialog shows the address to stream to and a QR code
of it. On the phone, PhotoFinish Camera scans the code and starts streaming: the camera list says
"recording" within seconds, and the picture is on screen.

**Why this priority**: Without it there is no camera at all.

**Independent Test**: The app on an emulator streams to PhotoFinish on the same computer, the
recorder records it, and the frames decode.

**Acceptance Scenarios**:

1. **Given** the add-camera dialog on the phone's connection, **Then** it shows the address and a
   QR code holding exactly that address.
2. **Given** the app has scanned the code, **When** the referee taps Start, **Then** PhotoFinish
   records the stream.
3. **Given** the Wi-Fi drops for a while, **Then** the app connects again by itself and the
   recording goes on, a gap between.

### User Story 2 - Each frame at the moment it was taken (Priority: P1)

The app keeps its clock in step with the computer's and writes into every frame the moment the
camera took it, on the computer's clock. PhotoFinish places each frame at that moment instead of
at the moment it arrived.

**Why this priority**: It is what a free app cannot do, and it makes a phone over Wi-Fi as
trustworthy for timing as a camera on a cable: the network's delay and jitter no longer move the
frames.

**Independent Test**: Frames recorded from the app carry their moments; moments are in order,
33 ms apart at 30 fps and 17 ms at 60, whatever the network does in between.

**Acceptance Scenarios**:

1. **Given** a stream with frame moments, **Then** each recorded frame's moment is the one the
   phone wrote, not its arrival.
2. **Given** a stream without them (another app), **Then** frames are placed by their arrival, as
   before.
3. **Given** the clock exchange cannot be made (a firewall blocks it), **Then** the app streams
   without frame moments and says so.

### User Story 3 - Settings a photo finish needs (Priority: P2)

The app offers the picture sizes and frame rates the phone gives it, 60 fps first where there is
one, a keyframe every second and a bitrate to match; it keeps the screen on, and dims it on a tap
while streaming.

**Why this priority**: These are the settings that were found to work by hand with a free app.

**Independent Test**: The choice of size and frame rate, given the phone's lists, is unit-tested;
on the Xiaomi 17 Ultra the app streams 1920x1080 at 60 fps.

**Acceptance Scenarios**:

1. **Given** a phone that offers 60 fps at 1080p, **Then** the app streams 60 fps.
2. **Given** one that offers 30 only, **Then** the app streams 30 and shows it.

### Edge Cases

- Streams of five hours and more: RTMP timestamps pass 0xFFFFFF ms after 4.6 hours and are sent
  as extended timestamps.
- A phone whose camera timestamps are on an unknown clock: the app finds which of its clocks they
  follow, or sends no frame moments.
- The network cannot keep up: frames are dropped up to the next keyframe, never sent late in a
  pile; the recording shows a gap.
- Two phones: each gets a port of its own (the dialog's rule since 0.4.0); the clock exchange uses
  the same port number over UDP.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The app is an Android app (`android/` in this repository), released with PhotoFinish
  as a signed APK, the way ChronometerAndroid releases its own.
- **FR-002**: It streams H.264 from the back camera over RTMP to the address it is given, with a
  keyframe every second, no audio, and connects again after a loss.
- **FR-003**: The address comes from a QR code PhotoFinish shows in the add-camera dialog, or is
  typed; it is an `rtmp://` URL, so other apps can scan the same code.
- **FR-004**: The app keeps its clock in step with the recorder's over UDP on the RTMP port number
  (`contracts/phone-stream.md`) and writes each frame's capture moment on the recorder's clock into
  the frame (an H.264 SEI message, same contract). It streams no frame without a moment once it
  has one, and none with one before it has a moment it can trust.
- **FR-005**: The recorder answers the clock exchange on the camera's port and, for a frame that
  carries a moment, records that moment.
- **FR-006**: The app offers the sizes and frame rates the camera and the encoder both support,
  60 fps first, and a bitrate that follows them; the choice is kept.
- **FR-007**: The screen stays on while streaming; a tap dims it, another brings it back.
- **FR-008**: Every user-facing string is in English, Russian and Kazakh.

### Key Entities

- **Pairing address**: `rtmp://<computer>:<port>/<path>`, shown and as a QR code.
- **Clock offset**: the recorder's clock minus the phone's camera clock, from the exchange with
  the shortest round trip among the recent ones.
- **Frame moment**: Unix microseconds on the recorder's clock, in each frame.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the Xiaomi 17 Ultra the app streams 1920x1080 at 60 fps to PhotoFinish, recorded
  at 59-60 fps with gaps under 1% of the time over a minute on the phone's own hotspot.
- **SC-002**: Frame moments recorded from the app step by the frame interval within 2 ms, whatever
  the arrival jitter.
- **SC-003**: The app's protocol code (RTMP, AMF, FLV, SEI, the clock exchange, the choice of
  settings) is covered by unit tests; PhotoFinish's side by its own.

## Assumptions

- Android 8 or newer (minSdk 26); the toolchain is pinned as in ChronometerAndroid.
- The QR code is read with ZXing (Apache-2.0); there is no other dependency for streaming.
- A frame's capture time comes from the camera (Camera2 sensor timestamps), which the encoder keeps
  as the frame's presentation time; the app checks which clock they follow.
- Short exposure for sharp wheels, streaming with the screen off and the Mi 11 Ultra's quirks are
  for the next iterations, tried on the phones.
