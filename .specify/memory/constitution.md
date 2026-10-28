<!--
Sync Impact Report
- Version: 1.0.0 -> 2.0.0 (maintainer's decisions of 2026-10-28, ChronometerPython issue #49,
  comment 8).
- Redefined: III "A correction is never lost and always traceable" becomes "Every change is on
  disk and traceable": the result is an editable output list saved to a file of its own, no
  longer a corrected copy of the source. V "Honest precision" becomes "Sub-frame time, labelled
  for what it is": a time between two frames, interpolated as a caliper reads between its marks
  or picked on a zoomed timeline, is allowed and recorded as such.
- Added: VI "Recording outlives the editor" (PhotoFinish now records live camera streams).
- Renumbered: VI tests -> VII, VII history -> VIII.
- Constraints: "offline first" now says that cameras may be reached over a local network.
- Templates: plan-template.md's "Constitution Check" gate reads these principles; no template
  needed changes.
-->

# PhotoFinish Constitution

PhotoFinish is the finish referee's video tool. A chronometer -- the desktop ChronometerPython or
the Android app, timed by hand, by a light beam or by chips -- records who crossed the line and
when. PhotoFinish records the finish cameras, lets the referee scroll the video while it is still
being recorded, and builds from the chronometer's crossings and the video a corrected list of
crossings of its own. It runs on the referee's own computer at the finish, without the internet.

## Core Principles

### I. The source is never touched

The timing files a chronometer writes are input only: never edited, rewritten, renamed or locked
against the chronometer that may still be appending to them. Everything PhotoFinish produces goes
to files of its own, so the record of the race stays exactly as it was taken.

### II. Timing never depends on PhotoFinish

PhotoFinish is a separate program. Video is heavy -- decoding, several cameras, computer vision --
and a crash, a hang or the operating system killing it for memory must cost the race nothing.
Nothing of a chronometer runs inside PhotoFinish or waits for it; the two exchange files only.

### III. Every change is on disk and traceable

The referee's result is an output list of crossings saved to a file of its own. A change to it is
on disk as soon as the referee makes it, so closing or losing the program loses nothing already
done. Each change is also journaled with what it replaced and where it came from: the line before
and after, the input line it was taken from, the camera, the frames and how the time was
obtained. The result can be explained and re-checked after the race.

### IV. The line format is a shared contract

PhotoFinish reads and writes crossing lines `number#time#action#`, which every chronometer writes
and FinishProtocolGeneratorPython reads. The time is `D H:M:S[.mmm]`: days since 1970-01-01 in
local standard time (no daylight-saving shift, unless the desktop chronometer's summer-time option
adds one), then hours, minutes and seconds without zero padding, and milliseconds, always three
digits, when recorded. A line taken from the input keeps its bytes until the referee changes it;
a time PhotoFinish sets is written the way the chronometers write it. Files from the older tools
are read as UTF-8, then cp1251, then Latin-1. A new field, a different separator or time format
is a change for every tool in the set, not for this repository alone.

### V. Sub-frame time, labelled for what it is

A frame gives a time to about half a frame interval (+-17 ms at 30 fps, +-2 ms at 240 fps).
Between two frames a time may be interpolated -- the rider's position before and after the line,
at a nearly steady speed, gives the moment of crossing the way a caliper reads between its marks
-- or picked by the referee on a timeline zoomed in between the frames. Such a time is allowed,
and it is always recorded as what it is: from which frames, by interpolation or by hand. The
program shows how every time was obtained and never passes an interpolated time off as a frame.

### VI. Recording outlives the editor

Live video is written to disk as it arrives, by a process separate from the window, in pieces
that are readable as soon as they are closed. A crash or a hang of the window, or of an analysis,
costs no recorded frame; a recorder that fails is started again and the gap is shown. Recording
never waits for the referee or for an analysis.

### VII. Behaviour is proven by tests

A behaviour change ships with a test that fails without it. Logic lives in Qt-free modules, which
the 90% coverage gate measures; the window is excluded from coverage, so a handler change needs a
Qt-level test through the `win` fixture in `tests/conftest.py`. Tests make the frames, streams and
files they need; no real race video or data is committed.

### VIII. Plain, attributable history

Files are ASCII. Commits follow Conventional Commits in one line with no trailers, because
release-please builds the changelog from them. Work is published under the owner's name with no
AI credit anywhere. Every change goes through a pull request from a branch off `origin/main`.

## Constraints

- Python 3.14 and PySide6, run through `uv`. Heavy dependencies (video decoding, computer vision)
  arrive with the feature that needs them, not ahead of it, and only with wheels for every release
  platform.
- Portable builds for Windows, macOS (Apple Silicon) and Linux; the program keeps its files next
  to itself (`app/paths.py`), so one copy of the folder serves one event.
- Offline first: nothing PhotoFinish does needs the internet. Cameras may be reached over a local
  network; models for analysis are files the referee downloads beforehand.

## Development Workflow

- A feature that changes a file format, what the referee sees or how PhotoFinish works with the
  other timing tools gets a specification in `specs/<NNN>-<short-name>/` made with the Spec Kit
  skills (`/speckit-specify`, `/speckit-plan`, `/speckit-tasks`, `/speckit-implement`). The
  maintainer reviews the specification and the plan before implementation starts. A change driven
  by an issue in another repository names it.
- `specs/app/` describes the program as it works today, from the first feature on. A change that
  alters described behaviour updates it in the same pull request.
- A bug fix or a small change needs no specification of its own.

## Governance

This constitution states the principles; `CLAUDE.md`, `AGENTS.md` and the skills they list hold
the detail and are kept consistent with it. The maintainer amends it through a pull request that
bumps the version -- MAJOR for a principle removed or redefined, MINOR for one added or materially
expanded, PATCH for wording -- and updates the Last Amended date.

**Version**: 2.0.0 | **Ratified**: 2026-10-28 | **Last Amended**: 2026-10-29
