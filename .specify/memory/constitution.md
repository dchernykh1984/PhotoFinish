<!--
Sync Impact Report
- Version: none -> 1.0.0 (first constitution, written with the repository's bootstrap).
- Principles: I-III are the maintainer's decisions of 2026-10-28 in ChronometerPython issue
  #49: video is its own program, it reads the timing files and never writes to them, and its
  result goes to files of its own. IV comes from the line format the sibling timing tools
  share; V from the precision analysis in #49 (frame rate bounds accuracy). VI-VII come from
  CLAUDE.md / AGENTS.md and the skills under .claude/skills and .agents/skills, which stay
  the detailed runtime guidance.
- Templates: plan-template.md's "Constitution Check" gate reads these principles; no
  template needed changes.
-->

# PhotoFinish Constitution

PhotoFinish is the finish referee's video tool. A chronometer -- the desktop
ChronometerPython or the Android app, timed by hand, by a light beam or by chips -- records
who crossed the line and when; PhotoFinish lets the referee check those crossings against
video from one or more cameras and correct their times. It runs on the referee's own
computer at the finish, usually without a reliable network.

## Core Principles

### I. The source is never touched

The timing files a chronometer writes are input only: never edited, rewritten, renamed or
locked against the chronometer that may still be appending to them. Everything PhotoFinish
produces goes to files of its own next to them, so the record of the race stays exactly as
it was taken, and dropping PhotoFinish's files undoes every correction.

### II. Timing never depends on PhotoFinish

PhotoFinish is a separate program. Video is heavy -- decoding, several cameras, later
computer vision -- and a crash, a hang or the operating system killing it for memory must
cost the race nothing. Nothing of a chronometer runs inside PhotoFinish or waits for it; the
two exchange files only.

### III. A correction is never lost and always traceable

A correction is on disk as soon as the referee makes it, so closing or losing the program
loses nothing already done. Each one records what it replaced and where it came from: the
crossing, the old time, the new time, the camera and the frame. The protocol can be
explained and re-checked after the race.

### IV. The line format is a shared contract

PhotoFinish reads crossing lines `number#time#action#`, the time as `D H:M:S.mmm`, which
every chronometer writes and FinishProtocolGeneratorPython reads; its corrected copy keeps
the same format, so the generator reads it unchanged. Files from the older tools are read as
UTF-8, then cp1251, then Latin-1. A new field, a different separator or time format is a
change for every tool in the set, not for this repository alone.

### V. Honest precision

A time read from video is as accurate as the frame it came from, about half a frame interval
(+-17 ms at 30 fps, +-2 ms at 240 fps). The program says which frame a time came from and
never presents the three decimals of the time format as accuracy the video does not have.

### VI. Behaviour is proven by tests

A behaviour change ships with a test that fails without it. Logic lives in Qt-free modules,
which the 90% coverage gate measures; the window is excluded from coverage, so a handler
change needs a Qt-level test through the `win` fixture in `tests/conftest.py`. Tests make
the frames and files they need; no real race video or data is committed.

### VII. Plain, attributable history

Files are ASCII. Commits follow Conventional Commits in one line with no trailers, because
release-please builds the changelog from them. Work is published under the owner's name with
no AI credit anywhere. Every change goes through a pull request from a branch off
`origin/main`.

## Constraints

- Python 3.14 and PySide6, run through `uv`. Heavy dependencies (video decoding, computer
  vision) arrive with the feature that needs them, not ahead of it.
- Portable builds for Windows, macOS (Apple Silicon) and Linux; the program keeps its files
  next to itself (`app/paths.py`), so one copy of the folder serves one event.
- Offline first: nothing PhotoFinish does needs a network.

## Development Workflow

- A feature that changes a file format, what the referee sees or how PhotoFinish works with
  the other timing tools gets a specification in `specs/<NNN>-<short-name>/` made with the
  Spec Kit skills (`/speckit-specify`, `/speckit-plan`, `/speckit-tasks`,
  `/speckit-implement`). The maintainer reviews the specification and the plan before
  implementation starts. A change driven by an issue in another repository names it.
- `specs/app/` describes the program as it works today, from the first feature on. A change
  that alters described behaviour updates it in the same pull request.
- A bug fix or a small change needs no specification of its own.

## Governance

This constitution states the principles; `CLAUDE.md`, `AGENTS.md` and the skills they list
hold the detail and are kept consistent with it. The maintainer amends it through a pull
request that bumps the version -- MAJOR for a principle removed or redefined, MINOR for one
added or materially expanded, PATCH for wording -- and updates the Last Amended date.

**Version**: 1.0.0 | **Ratified**: 2026-10-28 | **Last Amended**: 2026-10-28
