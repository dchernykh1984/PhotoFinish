# PhotoFinish

Photo finish for offline race timing: check the crossings a chronometer
recorded against video from the finish line and correct their times. It reads
the chronometer's results file and never writes to it; corrections go to files
of its own, which FinishProtocolGenerator reads in place of the original.

**Status:** bootstrap. The program is an empty window; the first feature is
specified in [`specs/001-video-refinement`](specs/001-video-refinement/spec.md).

## Download a ready-made app

Every release ships portable builds, so there is nothing to install and no
Python, uv or git needed. There is no release yet: the first one comes with
the first feature. Pick the file for your platform from the
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
uv run pre-commit install --hook-type commit-msg
```

After that pre-commit hooks will run automatically on every commit.

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
