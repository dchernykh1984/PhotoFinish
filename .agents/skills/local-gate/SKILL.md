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

Iterating on one file is much faster with the default addopts turned off:

```
uv run pytest tests/test_paths.py -q --no-cov -n0
```

`-n0` disables xdist, `--no-cov` skips the coverage gate. Run the full
`uv run pytest` once before pushing - the gate only means anything whole.

## Rules that bite

**`no-non-ascii`** rejects any non-ASCII byte in `.py`, `.md`, `.yml`,
`.toml`, `.json` and shell files, including everything under `.claude/`.
`CHANGELOG.md` (generated from commit text) and `uv.lock` are exempt, and so
are Spec Kit's generated files (`.specify/` except the constitution, and the
`speckit-*` skills), which no hook may rewrite. A typographic dash or a Russian
word in a docstring fails the commit. A PostToolUse hook warns as soon as one
lands in a file.

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
A PostToolUse hook runs `ruff format` and `ruff check --fix` on every Python
file that gets edited, so formatting complaints should not reach the commit.

**One version of each tool.** ruff, mypy and commitizen run from `uv.lock`:
pre-commit calls them through `uv run --frozen`, as do the edit hooks and CI,
so a bump is one lock change and mypy sees PySide6's types
(`ignore_missing_imports = true` covers the rest).

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
