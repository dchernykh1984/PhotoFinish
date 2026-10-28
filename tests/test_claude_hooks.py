"""The Claude edit hook, run as Claude Code runs it: a JSON payload on stdin.

A fake `uv` on PATH stands in for ruff and pre-commit and logs every call, so the
tests check what the hook runs and what it does with the answers, not the rules
themselves (ruff and pre-commit own those).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "post-edit.sh"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or not (shutil.which("bash") and shutil.which("jq")),
    reason="the hook is a bash script that needs jq",
)


def _run(
    project: Path,
    file: Path,
    *,
    ascii_report: str = "",
    ascii_exit: int = 0,
    backslashes: bool = False,
) -> tuple[str, list[list[str]]]:
    """Run the hook; return its stdout and the (tool, subcommand) of each uv call."""
    bin_dir = project / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = project / "uv.log"
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{log}"\n'
        'if [ "$4" = pre-commit ]; then\n'
        f"  printf '%s' '{ascii_report}'\n"
        f"  exit {ascii_exit}\n"
        "fi\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    # Claude Code on Windows passes native paths with backslashes.
    style = (lambda p: str(p).replace("/", "\\")) if backslashes else str
    result = subprocess.run(  # noqa: S603
        ["bash", str(HOOK)],  # noqa: S607
        input=json.dumps({"tool_input": {"file_path": style(file)}}),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": style(project),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        },
        check=True,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result.stdout, [call.split()[3:5] for call in calls]


def _file(project: Path, name: str) -> Path:
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    return path


RUFF_CHECK, RUFF_FORMAT, ASCII = (
    ["ruff", "check"],
    ["ruff", "format"],
    ["pre-commit", "run"],
)


def test_settings_run_one_post_edit_hook() -> None:
    settings = json.loads(
        (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    [entry] = settings["hooks"]["PostToolUse"]
    [hook] = entry["hooks"]
    assert entry["matcher"] == "Edit|Write"
    assert hook["command"].endswith('/.claude/hooks/post-edit.sh"')


def test_python_is_fixed_then_formatted_then_checked(tmp_path) -> None:
    out, calls = _run(tmp_path, _file(tmp_path, "code.py"))
    assert calls == [RUFF_CHECK, RUFF_FORMAT, ASCII]
    assert out == ""


def test_markdown_is_formatted_then_checked(tmp_path) -> None:
    _, calls = _run(tmp_path, _file(tmp_path, "note.md"))
    assert calls == [RUFF_FORMAT, ASCII]


def test_other_files_are_only_checked(tmp_path) -> None:
    _, calls = _run(tmp_path, _file(tmp_path, "notes.txt"))
    assert calls == [ASCII]


def test_ascii_report_reaches_the_user_and_claude(tmp_path) -> None:
    doc = _file(tmp_path, "docs/note.md")
    report = "Failed\ndocs/note.md:2:caf\ndocs/note.md:5:x\n"
    out, _ = _run(tmp_path, doc, ascii_report=report, ascii_exit=1)
    message = json.loads(out)
    assert message["systemMessage"].startswith("docs/note.md: 2 line(s)")
    assert message["hookSpecificOutput"] == {
        "hookEventName": "PostToolUse",
        "additionalContext": message["systemMessage"],
    }


def test_errors_that_name_no_line_stay_silent(tmp_path) -> None:
    report = "error: Failed to spawn: pre-commit\n"
    out, _ = _run(
        tmp_path, _file(tmp_path, "note.md"), ascii_report=report, ascii_exit=2
    )
    assert out == ""


def test_files_outside_the_project_are_ignored(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    out, calls = _run(project, _file(tmp_path, "outside.md"), ascii_exit=1)
    assert (out, calls) == ("", [])


def test_windows_style_paths_are_accepted(tmp_path) -> None:
    doc = _file(tmp_path, "note.md")
    out, calls = _run(
        tmp_path, doc, ascii_report="note.md:1:caf\n", ascii_exit=1, backslashes=True
    )
    assert calls == [RUFF_FORMAT, ASCII]
    assert json.loads(out)["systemMessage"].startswith("note.md: 1 line(s)")
