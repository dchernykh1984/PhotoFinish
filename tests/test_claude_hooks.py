"""The Claude edit hooks, run as Claude Code runs them: a JSON payload on stdin.

A fake `uv` on PATH stands in for pre-commit and ruff, so the tests check what
the hooks do with the answer, not the rule itself (pre-commit owns that).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or not (shutil.which("bash") and shutil.which("jq")),
    reason="the hooks are bash scripts that need jq",
)


def _run(hook: str, project: Path, file: Path, fake_uv: str) -> str:
    bin_dir = project / "bin"
    bin_dir.mkdir(exist_ok=True)
    uv = bin_dir / "uv"
    uv.write_text(f"#!/bin/sh\n{fake_uv}\n", encoding="utf-8")
    uv.chmod(0o755)
    payload = json.dumps({"tool_input": {"file_path": str(file)}})
    result = subprocess.run(  # noqa: S603
        ["bash", str(HOOKS / hook)],  # noqa: S607
        input=payload,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(project),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        },
        check=True,
    )
    return result.stdout


def test_ascii_hook_tells_the_user_and_claude(tmp_path) -> None:
    doc = tmp_path / "docs" / "note.md"
    doc.parent.mkdir()
    doc.write_text("x\n", encoding="utf-8")
    pygrep = "printf 'Failed\\ndocs/note.md:2:caf\\ndocs/note.md:5:x\\n'; exit 1"
    out = json.loads(_run("no-non-ascii.sh", tmp_path, doc, pygrep))
    assert out["systemMessage"].startswith("docs/note.md: 2 line(s)")
    assert out["hookSpecificOutput"] == {
        "hookEventName": "PostToolUse",
        "additionalContext": out["systemMessage"],
    }


def test_ascii_hook_is_silent_when_pre_commit_passes(tmp_path) -> None:
    doc = tmp_path / "note.md"
    doc.write_text("x\n", encoding="utf-8")
    assert _run("no-non-ascii.sh", tmp_path, doc, "exit 0") == ""


def test_ascii_hook_ignores_errors_that_name_no_line(tmp_path) -> None:
    doc = tmp_path / "note.md"
    doc.write_text("x\n", encoding="utf-8")
    broken = "echo 'error: Failed to spawn: pre-commit'; exit 2"
    assert _run("no-non-ascii.sh", tmp_path, doc, broken) == ""


def test_ascii_hook_ignores_files_outside_the_project(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("x\n", encoding="utf-8")
    pygrep = "printf 'outside.md:1:x\\n'; exit 1"
    assert _run("no-non-ascii.sh", project, outside, pygrep) == ""


def test_ruff_hook_fixes_before_it_formats(tmp_path) -> None:
    code = tmp_path / "code.py"
    code.write_text("x = 1\n", encoding="utf-8")
    log = tmp_path / "uv.log"
    _run("ruff-fix.sh", tmp_path, code, f'echo "$*" >> {log}')
    calls = log.read_text(encoding="utf-8").splitlines()
    assert [call.split()[4] for call in calls] == ["check", "format"]
    assert all(call.startswith("run --offline --no-sync ruff") for call in calls)
