"""The agent hooks check the same files for non-ASCII bytes as pre-commit does.

pre-commit's no-non-ascii hook is the rule; .codex/hooks/checks.json repeats
it for the two edit hooks (Codex reads it in post_edit.py, Claude through jq
in no-non-ascii.sh). A type or an exemption added to one and not the other
makes an agent warn about files pre-commit accepts, or stay quiet about files
it rejects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# pre-commit file types and the extensions they stand for in checks.json.
TYPE_EXTENSIONS = {
    "python": "py",
    "yaml": "ya?ml",
    "markdown": "md",
    "toml": "toml",
    "shell": "sh",
    "json": "json",
}


def _pre_commit_rule() -> tuple[str, str, list[str]]:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    global_exclude = re.search(r"^exclude: (\S+)$", config, re.MULTILINE)
    hook = config[config.index("id: no-non-ascii") :]
    hook_exclude = re.search(r"^\s+exclude: (\S+)$", hook, re.MULTILINE)
    types = re.search(r"^\s+types_or: \[(.+)\]$", hook, re.MULTILINE)
    assert global_exclude and hook_exclude and types
    return (
        global_exclude.group(1),
        hook_exclude.group(1),
        [t.strip() for t in types.group(1).split(",")],
    )


def test_checks_json_matches_the_pre_commit_rule() -> None:
    global_exclude, hook_exclude, types = _pre_commit_rule()
    checks = json.loads(
        (ROOT / ".codex" / "hooks" / "checks.json").read_text(encoding="utf-8")
    )
    assert checks["exclude"] == f"{hook_exclude}|{global_exclude}"
    extensions = "|".join(TYPE_EXTENSIONS[t] for t in types)
    assert checks["files"] == rf"\.({extensions})$"


def test_claude_hook_reads_checks_json() -> None:
    hook = (ROOT / ".claude" / "hooks" / "no-non-ascii.sh").read_text(encoding="utf-8")
    assert ".codex/hooks/checks.json" in hook
