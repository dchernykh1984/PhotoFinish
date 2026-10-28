---
name: review-cycle
description: How to run a review cycle on a branch or pull request here -- triaging findings, landing one commit per valid finding with a failing-first test, and posting the summary back to the PR. Includes the bug classes the sibling Qt apps keep producing. Use when asked to review, to do review cycles, or to act on review findings.
---

# Review cycle

A cycle is: review, triage, fix each valid finding in its own commit, then
report.

## Reviewing

Review the PR diff or the branch against its upstream base, then the
questions in `reviewing-a-change`. Effort `high` is the useful default here:
the expensive bugs are the ones that only show up in a specific referee
workflow.

## Triage

Take every finding seriously, but check the claim against the code before
acting -- a report can be wrong about the mechanism while pointing at a real
problem, or right about the mechanism and irrelevant in practice. State
plainly which findings are valid and why, and fix them all rather than the
convenient subset.

A finding is worth a commit when it changes what the program does for a
referee: a source file touched, a correction lost, a wrong time, a crash, an
unattended path that blocks on a dialog. Cosmetic notes about a comment or a
name go in with the nearest real fix.

## Fixing

One commit per finding, each with a test that fails without it (see
`shipping-a-change` for the stash check). Keep the commit message about the
user-visible effect, not the mechanism.

## Reporting

Post one comment per cycle with a table of finding to fix commit, so the
reviewer can follow what was accepted and how it was closed:

```bash
gh pr comment <number> --body "$(cat <<'BODY'
### Review cycle 1
| Finding | Fix |
| --- | --- |
| ... | `<sha>` ... |
BODY
)"
```

Then run the next cycle against the fixed branch. Fixes introduce their own
bugs, so a second cycle is not a formality.

## Bug classes the sibling Qt apps keep producing

Each of these has shipped at least once in ChronometerPython or
StartProtocolMakerPython. Check them first.

- **Exceptions escaping into a Qt slot.** PySide6 terminates the application
  on an unhandled exception in a slot, so anything reached from a timer or a
  signal must not raise. A failure while reading a file or a stream arrives as
  a bare `OSError`.
- **Modal dialogs on unattended paths.** A `QMessageBox` is fine for a button
  the referee just pressed. On a timer path it blocks the program until
  someone clicks it; report there through a status label instead.
- **Timer and debounce state that outlives its subject.** Opening a different
  file or recording, or switching a mode off, must clear whatever was queued
  for the previous one, or the queued work runs against the new one.
- **Widget contents treated as user input.** A value the program wrote into a
  field (a computed time) must not be saved as if the referee had typed it.
  Track what was typed (`textEdited` fires only for real edits) when the two
  can diverge.
