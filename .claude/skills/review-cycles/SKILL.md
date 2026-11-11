---
name: review-cycles
description: A series of review cycles on a pull request here -- how each cycle counts its findings by severity, the table the maintainer asks for, when the series has converged, and what may follow it (a merge, a release). Use when asked for several review cycles ("ten cycles of review"), for the table of findings, or whether a branch is ready to merge or release after its reviews.
---

# A series of review cycles

The maintainer asks for review cycles by number -- "a dozen", "ten" -- and then
for a table. Each cycle is the `review-cycle` skill: review, triage, a commit
per valid finding with a test that fails without it, a comment on the PR. This
skill is the series around it.

## Before the first cycle

- Everything asked for is built and pushed, and the pipeline is green: a cycle
  spent on code that does not build is a cycle lost.
- Note the head: each cycle reviews the whole PR as the last one left it.

## Each cycle

1. Review the whole pull request, not only the last fixes (`code-review` at
   effort high, then the questions of `reviewing-a-change`): the bug a fix
   brings is the next cycle's to find.
2. Weigh each finding against the code before counting it:
   - **High** -- a referee's result at stake: a wrong time, a crossing lost or
     changed, a recording that stops or a frame placed wrong, a crash, the
     chronometer's file touched, a stream cut mid-race.
   - **Medium** -- a real workflow that fails or misleads, seen and recoverable.
   - **Low** -- an edge that is rarely met, a word that misleads, a test that
     does not pin what it claims.
   - **Not valid / won't fix** -- wrong about the code, already handled, or a
     change of behaviour the maintainer would have to decide; say which, and why.
3. Fix every valid finding in a commit of its own, its test first (the stash
   check of `shipping-a-change`); the local gate (`local-gate`); push.
4. Comment on the PR: each finding, its severity, its commit or why none.
5. Add the cycle's row to the table.

## The table

| Cycle | Found | High | Medium | Low | Fixed | Not valid / won't fix |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 | 4 | 4 | 2 | 10 | 0 |

Found is every finding; High, Medium and Low are the valid ones; Fixed is those
that got a commit. A finding counts in the cycle that found it, whenever it is
fixed; a cycle that found nothing new is a row of zeroes, never left out. After
the last cycle the table goes on the PR and to the maintainer.

## Converged, or not

The series has converged when its last cycles find no High and a Medium or
two at most, and what is left repeats earlier findings or is not valid. A
review at high effort always finds something: near zero is the measure, not
zero. Say plainly whether it converged.

## What may follow

- A merge only when the maintainer asked for it, on a green pipeline: an
  ordinary PR with `--admin`, as the maintainer cannot approve their own.
- A release only when asked, and only as `shipping-a-change` says: the release
  PR's pipeline approved and green, the PR approved, merged without `--admin`,
  the release build waited for and its assets checked.
- A series that did not converge is said, and the maintainer decides: no merge
  or release on the count of cycles alone.
