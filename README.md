# PhotoFinish

Photo finish for offline race timing: check the crossings a chronometer
recorded against video from the finish line and correct their times. It reads
the chronometer's results file and never writes to it; corrections go to files
of its own, which FinishProtocolGenerator reads in place of the original.

The finish camera is a phone on a tripod: PhotoFinish Camera, the phone app
released with it, sends the video to PhotoFinish over the local network, each
frame with the moment it was taken, and PhotoFinish records it (see
[The camera: a phone](#the-camera-a-phone)).

It records each finish camera in a process of its own that keeps recording when
the window is gone, shows every camera at one moment, follows the chronometer's
file as it grows, and keeps the referee's crossings -- added from a frame,
corrected, or read between two frames like a caliper -- in an output file with a
journal of every change. An experimental helper, off by default, marks where riders
pass -- by motion, or by a detection model downloaded when chosen -- and suggests
crossings to accept or dismiss. What it does, in full: [`specs/app`](specs/app/README.md);
a first session with the test camera:
[quickstart](specs/001-video-refinement/quickstart.md).

## The camera: a phone

1. Install PhotoFinish Camera on the phone (Android 8 or newer):
   `photofinish-camera-<version>.apk` from the
   [latest release](https://github.com/dchernykh1984/PhotoFinish/releases/latest);
   allow the browser or file manager to install apps when Android asks.
2. Put the phone and the computer on one network: the phone's own hotspot will do.
3. In PhotoFinish: Cameras -> Add... The dialog shows the address to stream to,
   such as `rtmp://10.0.0.5:1935/live/cam1`, and the same address as a QR code.
   Tick more lenses -- Ultra-wide, Telephoto, Front -- to record them too: each
   is a camera of its own, and the code holds them all. OK.
4. In PhotoFinish Camera: "Scan PhotoFinish's code", pick the picture size and
   the frame rate (60 fps first, when the phone gives it), "Start". The app says
   how many frames a second it sends and how closely its clock is in step with
   PhotoFinish's; the camera list says "recording", and the window's top right
   corner turns to a green RECORDING. Red NOT RECORDING there, wherever in the
   video you are, means a camera's stream is lost.
5. One camera shows the chosen camera alone, large: Ctrl+1 to Ctrl+9 pick it,
   Ctrl+Up and Ctrl+Down switch, Ctrl+0 shows them all side by side again.

The app keeps the phone's camera clock in step with the recorder's and writes
each frame's moment into the frame, so Wi-Fi delays do not move frames on the
timeline. A free streaming app that sends RTMP still works -- Larix Broadcaster
was tried at 2560x1440 and 60 fps; its free version writes "TEST STREAM" over the
picture -- set to 60 fps, about 10 Mbit/s and a keyframe a second; its frames are
placed by when they arrive.

The phone runs for hours: keep it on a charger and out of direct sun, dim its
screen, and keep the sun out of the frame.

Action cameras were tried and dropped: their live video is a low-quality preview
(the SJCAM SJ10 Pro: 1280x720 at about 0.9 Mbit/s over its own Wi-Fi, with seconds
without frames, and no video over its cable).

## Download a ready-made app

Every release ships portable builds, so there is nothing to install and no
Python, uv or git needed. Pick the file for your platform from the
[latest release](https://github.com/dchernykh1984/PhotoFinish/releases/latest):

| Platform | File |
| --- | --- |
| Windows (Intel/AMD) | `PhotoFinish-windows-x64.exe` |
| Windows (ARM) | `PhotoFinish-windows-arm64.exe` |
| macOS (Apple Silicon) | `PhotoFinish-macos-arm64.zip` |
| Linux (Intel/AMD) | `PhotoFinish-linux-x86_64` |
| Linux (ARM64) | `PhotoFinish-linux-aarch64` |

The builds are not code-signed, so every system needs a one-off nudge before the
first launch. Each step below is done once per download, not on every start.

### macOS

Only Apple Silicon (M1 and newer) is supported - there is no Intel build.

Unpack the archive, then clear the quarantine flag that macOS puts on downloaded
files:

```bash
xattr -dr com.apple.quarantine "/path/to/PhotoFinish.app"
```

After that the app opens with a normal double-click. Without it macOS refuses to
start the app, because it is unsigned.

The flag stays cleared. Copying or moving the app on the same Mac keeps it clear,
so there is no need to repeat this for every copy. It only comes back when the app
arrives from outside again: a fresh download, AirDrop, or unpacking a
newly downloaded archive.

Rather not use a terminal? Ctrl-click the app, choose **Open**, then **Open**
again in the dialog. macOS 15 Sequoia dropped that shortcut - there, go to System
Settings -> Privacy & Security, scroll down to the notice about the blocked app
and press **Open Anyway**.

Taken this way, the quarantine flag stays on - on the app and on every copy
made of it - and macOS may run the app from a temporary read-only copy (App
Translocation), where the files PhotoFinish keeps next to itself cannot be
written. Use it for a first look only, and clear the flag with the command
above before the app keeps any files at an event.

### Windows

Run the `.exe` directly. SmartScreen warns that the publisher is unknown: choose
**More info**, then **Run anyway**.

### Linux

Make the file executable and run it:

```bash
chmod +x PhotoFinish-linux-x86_64
./PhotoFinish-linux-x86_64
```

This is a GUI application, so it needs a graphical session. If it fails to start
with an error about missing Qt libraries, install them:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libxcb-cursor0
```

### Where to keep it

The program reads and writes its files **next to itself**, so give
it a folder of its own rather than a shared downloads directory. On macOS the
files land next to the `.app` bundle, in the folder that contains it.

The session is `data/session.json` and each camera's recording is in
`video/<camera>/`, so keep the folder on a disk with room: about 4 GB an hour
for each phone sending 9 Mbit/s (1440p at 60 fps).

This is also how you run several events side by side: copy the folder per event,
and each copy keeps its own data. A symlink or a Finder alias will not work for
that - it resolves back to the original, so every "copy" would end up sharing one
set of files. Use real copies.


## Setup

### 1. Download the project

Install Git if you don't have it:

- **macOS:** `brew install git`
- **Linux (Ubuntu / Debian):** `sudo apt install git`
- **Windows:** download from [git-scm.com](https://git-scm.com/downloads) and run the installer

Then clone the repository:

```bash
git clone https://github.com/dchernykh1984/PhotoFinish.git
cd PhotoFinish
```

All subsequent commands should be run from the `PhotoFinish` folder.

### 2. Install Python 3.14

This project requires **Python 3.14**; `uv` installs a matching interpreter automatically, but you can also install it yourself as shown below.

**macOS**

```bash
brew install python@3.14
```

If you don't have Homebrew yet, install it first from [brew.sh](https://brew.sh).

**Linux (Ubuntu / Debian)**

The system `python3` package is usually not 3.14. Install it via the deadsnakes PPA:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.14 python3.14-venv
```

**Windows**

Download the **Python 3.14** installer from [python.org/downloads](https://www.python.org/downloads/) and run it. On the first screen, check **"Add Python to PATH"** before clicking Install.

Verify the installation in a terminal:

- **macOS / Linux:** `python3.14 --version`
- **Windows:** `py -3.14 --version`

The output should start with `Python 3.14`.

### 3. Install uv

**macOS / Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows**

Open **PowerShell** and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal afterwards so `uv` is on your `PATH`.

### 4. Create virtual environment and install dependencies

```bash
uv sync
```

### 5. Set up pre-commit hooks

```bash
uv run pre-commit install
```

That installs both the file checks and the commit-message check
(`default_install_hook_types`), and they run automatically on every commit.

To run all checks manually across all files:

```bash
uv run pre-commit run --all-files
```

## Running the application

```bash
uv run python -m app.main
```

> **Note:** use `-m app.main`, not `python app/main.py`. The `-m` flag adds the
> project root to `sys.path` so that the `app` package is importable.

## Specifications

Changes to file formats, to what the referee sees and to how PhotoFinish works
with the other timing tools start as a specification, written with
[Spec Kit](https://github.com/github/spec-kit): see [`specs/`](specs/README.md)
and the [constitution](.specify/memory/constitution.md).

## Contributing

Before requesting a review, make sure the CI pipeline passes on your pull request. Once the pipeline is green, request a review from [@dchernykh1984](https://github.com/dchernykh1984).
