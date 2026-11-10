---
name: local-gate
description: Running the checks CI runs before pushing, plus the ruff, mypy, coverage and ASCII rules in this repo that fail a commit most often. Use before every push or commit here.
---

# The local gate

Everything CI checks runs on this machine, so there is no excuse for pushing
red.

```
uv run pre-commit run --all-files     # pre-commit job
uv run pytest                          # tests job
```

A change under `android/` also runs the phone app's gate (the `android` job; JDK
17 and the Android SDK, as the `android-app` skill sets them):

```
cd android && ./gradlew ktlintCheck detekt lintDebug testDebugUnitTest koverVerify assembleDebug assembleRelease
```

Iterating on one file is much faster with the default addopts turned off:

```
uv run pytest tests/test_paths.py -q --no-cov -n0
```

`-n0` disables xdist, `--no-cov` skips the coverage gate. Run the full
`uv run pytest` once before pushing - the gate only means anything whole.

## Rules that bite

**`no-non-ascii`** rejects any non-ASCII byte in `.py`, `.md`, `.yml`,
`.toml`, `.json`, Kotlin and shell files, including everything under `.claude/`;
the phone app's `values-ru` and `values-kk` strings are XML and carry their
languages.
`CHANGELOG.md` (generated from commit text) and `uv.lock` are exempt, and so
are Spec Kit's generated files (`.specify/` except the constitution, and the
`speckit-*` skills), which no hook may rewrite. A typographic dash or a Russian
word in a docstring fails the commit. The edit hooks run that same pre-commit
rule on every file an agent edits and warn at once.

**`mixed-line-ending --fix=lf`** plus `.gitattributes` (`* text=auto eol=lf`)
keep the tree LF on every platform. Do not fight it from Windows.

**ruff** (line length 88) with `E W F I N C90 UP B S PTH RUF` selected. The
ones that come up most:

| Rule | What it wants |
| --- | --- |
| `PTH` | `pathlib`, never `os.path` or bare `open()`. |
| `S` (bandit) | A deliberate `subprocess` or `urllib` call carries a `# noqa` naming the rule (`S603`, `S310`). |
| `C90` | Cyclomatic complexity max 10 - split the function. |
| `B` | No mutable default args, no bare `except`. |

`tests/**` may use `assert` and fake secrets (`S101`, `S105`, `S106` ignored).
The edit hooks run `ruff check --fix` and then `ruff format` on every edited
Python file, and `ruff format` on Markdown (its code blocks), so formatting
complaints should not reach the commit.

**One version of each tool.** ruff, mypy and commitizen come from `uv.lock`:
pre-commit and CI call them through `uv run --frozen`, which syncs the
environment first, so a bump is one lock change and mypy sees PySide6's types
(`ignore_missing_imports = true` covers the rest). The edit hooks run the ruff
already installed (`--no-sync`: a hook never installs anything), so run
`uv sync` after pulling a lock change, or they format with the previous ruff.

## Coverage

The gate is **90%**, measured over `app/` with `app/main.py` and
`app/main_window.py` omitted. That omission is deliberate: it keeps the gate on
the Qt-free modules, so put logic there rather than in the window.

The UI is still tested - `tests/conftest.py` builds a real `MainWindow` under
`QT_QPA_PLATFORM=offscreen` through the `win` fixture. When you touch a handler
in `main_window.py`, add a test there; it will not show up in the coverage
number but it is what keeps the handlers from drifting. See the
`qt-window-tests` skill.

Tests must never write into the repo, hit the network or need a real race
video: write into `tmp_path` and generate the frames or files a test needs.
