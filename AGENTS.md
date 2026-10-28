# PhotoFinish - project guide for coding agents

Photo finish for offline race timing: a PySide6 desktop app in which the finish
referee checks the crossings a chronometer recorded against video from one or
more cameras and corrects their times. It reads the chronometer's files and
never writes to them; its corrections go to files of its own. Files are the
source of truth, and nothing here needs a network.

The program is an empty window today. The first feature is specified in
`specs/001-video-refinement/spec.md`; the design discussion behind it is
ChronometerPython issue #49.

## Layout

| Path | What lives there |
| --- | --- |
| `app/main.py` | Entry point (`uv run python -m app.main`). |
| `app/main_window.py` | The Qt UI. |
| `app/paths.py` | Resolves where data lives (see below). |
| `tests/` | pytest; `conftest.py` holds the offscreen Qt `win` fixture. |
| `specs/` | Specifications; the principles are in `.specify/memory/constitution.md`. |

Keep logic that is not UI - parsing timing lines, time and frame arithmetic,
writing corrections - in Qt-free modules under `app/`: that is what the
coverage gate measures.

## Where the app keeps its data

`app/paths.py:base_dir()` returns the folder that contains the runnable when
frozen (PyInstaller; on macOS the folder containing the `.app` bundle) and the
current working directory in development. Resolve every data file with
`app_path()`, so one copied folder per event keeps its own files: relative paths
are based on that folder, absolute paths stay unchanged, and config values keep
their original spelling. Finder may launch a macOS app with `/` as its working
directory.

## The other timing tools

| Tool | Relation |
| --- | --- |
| ChronometerPython, ChronometerAndroid | Write the results file PhotoFinish reads: `number#time#action#`, the time as `D H:M:S[.mmm]` (days since 1970-01-01 in local standard time - no daylight-saving shift unless the desktop chronometer's summer-time option is on; hours, minutes and seconds not zero-padded; milliseconds, when recorded, always three digits). |
| FinishProtocolGeneratorPython | Reads the corrected copy PhotoFinish writes, in the same format. |
| cycling-site | Not talked to; the chronometers upload, the generator publishes. |

The chronometer's files are input only: open them read-only and expect them to
grow while PhotoFinish has them open.

## Commands

```bash
uv sync                                  # install
uv run python -m app.main                # run the app (never python app/main.py)
uv run pytest                            # tests, -n auto, coverage gate 90%
uv run pre-commit run --all-files        # everything CI's pre-commit job runs
```

`uv sync` installs the dev group by default (`tool.uv.default-groups = ["dev"]`);
the `build` group holds PyInstaller for the release builds.
Python is pinned to 3.14.

## Conventions

- **ASCII only.** A pre-commit hook rejects non-ASCII in `.py`, `.md`, `.yml`,
  `.toml`, `.json` and shell files (`CHANGELOG.md`, `uv.lock` and Spec Kit's
  generated files are exempt). No typographic dashes, no quotes-as-glyphs, no
  Cyrillic in files. Discussion happens in whatever language the user writes in.
- **LF line endings** everywhere, enforced by `.gitattributes` and pre-commit.
- **ruff** with a broad rule set (line length 88, bugbear, bandit, pathlib,
  pyupgrade, mccabe max-complexity 10) and **mypy**. Run them via pre-commit.
- **Conventional commits, one line, no body, no trailers.** `cz check` runs on
  every PR. Never add a `Co-Authored-By` line or assistant attribution to a commit,
  a PR body or an issue comment.
- **Coverage gate is 90%**, with `app/main.py` and `app/main_window.py` omitted
  from the measurement. UI handlers are still covered by Qt-level tests through
  the `win` fixture - add one there when you touch a handler.
- **Stay in scope.** If you spot an unrelated problem, report it and let the
  user decide.

## Specifications

Changes to a file format, what the referee sees or how PhotoFinish works with
the other timing tools start as a specification: see
[`specs/README.md`](specs/README.md) and the constitution in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md). The Spec
Kit skills (`speckit-specify`, `speckit-plan`, `speckit-tasks`,
`speckit-implement` and the rest) drive that flow.

## Skills

- `shipping-a-change` - branch, failing-first test, commit, PR, the six checks.
- `local-gate` - the checks CI runs and the rules that fail a commit most often.
- `reviewing-a-change` - the failure modes that matter for this tool.
- `review-cycle` - review a branch or PR and land the fixes.
- `qt-window-tests` - how to test the PySide6 window.

## Release

release-please owns versioning: merging `feat:` or `fix:` commits to `main`
opens a release PR, and merging that cuts the tag, builds the portable apps for
every platform and attaches them to the GitHub release. Do not bump the version
in `pyproject.toml` by hand.

## Coding agent context

Codex reads this `AGENTS.md` at startup and discovers skills in `.agents/skills/`.
Read the relevant skill before using its workflow. Claude keeps `CLAUDE.md`,
`.claude/skills/` and its own settings; update both guides and skill copies when a
shared convention changes.

`.codex/hooks.json` runs pre-commit's own `no-non-ascii` hook on the files an
`apply_patch` edited, including multi-file patches and moves, so the rule lives
only in `.pre-commit-config.yaml`; the Claude hook does the same. Python edits are
also formatted and linted with the project ruff toolchain.
Run `python3 .codex/hooks/test_post_edit.py` to verify the handler; pre-commit
runs these tests too. Post-edit hooks report completed edits; they do not undo
them. Shell writes still require the pre-commit gate.

Project hooks require a trusted project and review of the current hook definition
in `/hooks`. Changed definitions require renewed review, and hooks must remain
enabled in local Codex configuration. Repository files do not grant trust or
change user-level settings. Existing Claude hooks remain in place.

Claude permission allowlists and attribution settings are not Codex settings.
Codex uses its own native permissions and approvals. An explicit user request to
push and open a pull request authorizes those actions for that task; never merge,
tag or release unless the user asks for it.
