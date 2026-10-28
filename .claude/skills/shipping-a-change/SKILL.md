---
name: shipping-a-change
description: The path from a change to a merged PR in this repository - branching, a failing-first test, one-line conventional commits, the local gate, gh, the six CI checks, and how a release is cut. Use whenever asked to fix, implement, or open a pull request here.
---

# Shipping a change

## The loop

1. Branch off `origin/main` (fetch first), never off whatever is checked out:
   local branches here are often unmerged PRs. Branch names follow the commit
   type: `fix/...`, `feat/...`, `chore/...`, `ci/...`, `docs/...`,
   `refactor/...`. Never commit to `main`.
2. Implement in **separate commits, one per concern**; a review finding gets
   its own commit.
3. Prove a behaviour change with a test that fails without it (below).
4. Re-read the diff fresh before pushing - see the `reviewing-a-change` skill.
5. Run the local gate (see the `local-gate` skill). Do not push red.
6. Push and open the PR with `gh`.
7. Hand the PR link back. **Do not merge** unless merging was asked for. The
   author writes in Russian and the difference between asking for a pull
   request and asking for a release is one word - re-read the request.

## A failing-first test

Check that the new test really fails without the change instead of assuming
it does:

```
git stash push app/<module>.py
uv run pytest tests/<test_file>.py -q --no-cov -n0 -k <selector>   # expect failures
git stash pop
```

A test that passes both ways can still be worth keeping when it pins
behaviour that must not regress - just do not count it as proof.

## Commit messages

Single-line conventional commits. **No body, no trailers, and never a
`Co-Authored-By` line or any Claude attribution** - the same goes for PR
bodies. `.claude/settings.json` already blanks both attributions, so nothing
should append them; if one appears, strip it.

```
fix: keep the corrected copy when the source gains a line
test: share the qt window fixture through a conftest
ci: cap the build job runtime with a timeout
```

`cz check --rev-range origin/main..HEAD` runs on every PR, so a message that
does not parse fails CI. `feat:` and `fix:` drive the release-please version
bump; `chore:`, `ci:`, `docs:`, `test:`, `refactor:` do not.

Merges to `main` are done with **rebase**, so every commit subject you write
ends up in the public history and in the changelog. Write them for that reader.

## Opening the PR

```
git push -u origin <branch>
gh pr create --title "<plain sentence, no type prefix>" --body "<what and why>"
```

PR titles read as plain sentences ("Keep the corrected copy when the source
gains a line"); the conventional prefix lives in the commits. A body reviewers
can act on says why (the behaviour and its mechanism), what each commit
changes, the decisions taken knowingly, and what the tests cover.

## The checks

Six run on every PR:

| Check | What it does |
| --- | --- |
| `pre-commit` | The whole pre-commit config on all files. |
| `commitizen` | `cz check` over `origin/main..HEAD`. |
| `tests` | `uv run pytest` on Linux with the Qt runtime libs installed. |
| `audit` | `pip-audit` over the exported runtime dependencies. |
| `build / targets` | Computes the build matrix. |
| `build / build (ubuntu-22.04, linux-x86_64)` | PyInstaller smoke build. |

Take the verdict from the rollup, not from `gh pr checks`: its per-check
status lags and can still say `pending` long after the job has finished.
Read `.status`, not `.conclusion` - a running check reports `conclusion` as an
empty string, which jq's `//` does not treat as missing. Everything is done
when this prints `true`:

```
gh pr view <N> --json statusCheckRollup \
  --jq '[.statusCheckRollup[].status] | all(. == "COMPLETED")'
```

Then read each conclusion, and check that the run belongs to the current head
SHA - a fresh push starts a new run while the old one still shows as passed:

```
gh pr view <N> --json headRefOid,statusCheckRollup \
  --jq '.headRefOid, (.statusCheckRollup[] | "\(.name // .context): \(.conclusion)")'
```

If a check fails, fix it with another commit on the same branch; do not
force-push over a reviewed history.

## Releasing

Only when explicitly asked. release-please opens a `chore(main): release X.Y.Z`
PR after `feat:` or `fix:` commits land on `main`; merging it cuts the tag,
syncs `uv.lock` to the new version, builds the portable apps for every platform
and attaches them to the GitHub release. Never bump `pyproject.toml` by hand.

Confirm the assets landed:

```
gh release view vX.Y.Z --json assets --jq '.assets[].name'
```

## Reporting back

Lead with the conclusion: what changed, what the user has to do differently,
and anything found but deliberately left alone. Skip the derivation unless it
changes what they do next.
