---
name: reviewing-a-change
description: What to look for when reviewing a diff in this repository - the failure modes that matter for a photo finish tool working beside live race timing. Use before pushing your own change and when asked to review a PR or a diff here.
---

# Reviewing a change

`/code-review` handles the generic pass. This skill is about what is specific
to PhotoFinish: it works beside a chronometer that may still be recording, on
files that hold a race nobody can run again, with video heavy enough to kill a
process. Read the diff asking what it does when something goes wrong, not
whether the happy path works. The principles behind these questions are in
`.specify/memory/constitution.md`.

## The questions that find real bugs here

**Can it write to the chronometer's files?** They are input only. An open for
writing or appending, a rename, a "save back" or a lock on a results file is a
bug, however convenient. Everything PhotoFinish produces goes to its own files.

**Can a correction be lost?** A correction is on disk once the referee has
made it. Look for corrections held only in memory until a later save, for a
write that can leave a half-written file (write a temporary file and rename it
over the old one), and for an `except` that swallows an `OSError`.

**Does the referee find out?** A failure the referee does not see is found
after the protocol is published. Report it where they are looking.

**Does it block or bloat?** Decoding video, scanning frames and reading large
files stay off the UI thread. Never load a whole recording into memory:
running out of memory is the failure the separate program exists to absorb,
not one to cause.

**Is the time honest?** A time from video comes from a frame. It must come
from that frame's own timestamp, not from its index times a nominal frame rate
(phones record at a variable rate), and a camera's offset is applied once.

**Does it change a format?** `number#time#action#` with the time as
`D H:M:S.mmm` is written by every chronometer and read by
FinishProtocolGeneratorPython. Adding a field, reordering, or changing the
separator is a change for the whole set of tools, even though nothing in this
repo complains.

**Are the reads still tolerant?** Results files from the older C++ tools turn
up in cp1251: read UTF-8, then cp1251, then Latin-1. A file still being
appended to may end in a partial line.

**Does it change where data lives?** `app/paths.py:base_dir()` is what makes
one copied folder per event work. Resolve runtime files with `app_path()`,
never against the current working directory: Finder can launch a macOS app
from `/`.

## Tests

A change to a Qt-free module needs a unit test - that is what the 90% coverage
gate measures. A change to a `main_window.py` handler needs a Qt-level test
through the `win` fixture, even though the window is omitted from coverage.
Tests build their own frames and files; no real race data.

## Scope

Report what you find outside the scope of the task; do not fix it. An
unrequested edit next to a requested one is hard to review and easy to
distrust.
