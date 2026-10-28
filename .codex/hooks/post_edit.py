#!/usr/bin/env python3
"""Format edited Python and report non-ASCII bytes after a Codex apply_patch.

The ASCII rule - file types, exemptions, pattern - lives only in
.pre-commit-config.yaml; this hook asks pre-commit to apply it to the edited files.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add File|Update File|Move to): ([^\r\n]+)\r?$", re.MULTILINE
)
# pygrep reports each offending line as "path:line:text".
LINE_HIT = re.compile(r"\d+:")


def edited_paths(payload: dict[str, Any], root: Path) -> list[Path]:
    """Resolve patch and legacy edit paths within this repository."""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []
    raw_paths = []
    raw_path = tool_input.get("file_path")
    if isinstance(raw_path, str):
        raw_paths.append(raw_path)
    command = tool_input.get("command")
    if isinstance(command, str):
        raw_paths.extend(PATCH_PATH.findall(command))
    cwd = Path(payload.get("cwd") or root).resolve()
    paths = []
    for name in raw_paths:
        path = (cwd / name).resolve()
        if path.is_relative_to(root) and path.is_file() and path not in paths:
            paths.append(path)
    return paths


def violations(paths: list[Path], root: Path) -> list[str]:
    """Run pre-commit's own no-non-ascii hook on the edited files.

    Without uv or a synced environment nothing is reported: the commit-time gate
    still applies.
    """
    uv = shutil.which("uv")
    if not paths or uv is None:
        return []
    names = [path.relative_to(root).as_posix() for path in paths]
    command = [uv, "run", "--offline", "--no-sync", "pre-commit", "run"]
    try:
        result = subprocess.run(  # noqa: S603
            [*command, "no-non-ascii", "--files", *names],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):  # fmt: skip
        return []
    if result.returncode == 0:
        return []
    lines = result.stdout.splitlines()
    return [
        name
        for name in names
        if any(
            line.startswith(f"{name}:") and LINE_HIT.match(line[len(name) + 1 :])
            for line in lines
        )
    ]


def format_python(paths: list[Path], root: Path) -> None:
    """Keep edited Python ruff-clean and Markdown code blocks formatted.

    The same split as the pre-commit ruff hooks: Python is fixed and formatted,
    Markdown only formatted. --force-exclude keeps ruff off the files its config
    excludes (Spec Kit's generated files).
    """
    python_paths = [str(path) for path in paths if path.suffix == ".py"]
    markdown_paths = [str(path) for path in paths if path.suffix == ".md"]
    uv = shutil.which("uv")
    if not (python_paths or markdown_paths) or uv is None:
        return
    # Fix first, then format, as pre-commit does: a fix can change the layout.
    steps = (
        (["check", "-q", "--fix"], python_paths),
        (["format", "-q"], python_paths + markdown_paths),
    )
    for action, files in steps:
        if not files:
            continue
        try:
            result = subprocess.run(  # noqa: S603
                [
                    uv,
                    "run",
                    "--offline",
                    "--no-sync",
                    "ruff",
                    *action,
                    "--force-exclude",
                    "--",
                    *files,
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):  # fmt: skip
            print(
                "Ruff unavailable; run the pre-commit gate before committing.",
                file=sys.stderr,
            )
            return
        if result.returncode:
            print(
                "Ruff needs attention; run the pre-commit gate before committing.",
                file=sys.stderr,
            )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    paths = edited_paths(payload, ROOT)
    format_python(paths, ROOT)
    problems = violations(paths, ROOT)
    if not problems:
        return 0
    print(
        "Non-ASCII bytes in " + ", ".join(problems) + ". Fix before committing.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
