"""Tool versions must agree wherever they are pinned.

The edit hooks run ruff from uv.lock, pre-commit runs the revs in
.pre-commit-config.yaml, and CI installs commitizen by its own pin. Dependabot
updates only the lock, so a bump that reaches one place and not the others is
caught here, not as formatting that flips between two ruff versions.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK_PACKAGES = {
    "astral-sh/ruff-pre-commit": "ruff",
    "pre-commit/mirrors-mypy": "mypy",
    "commitizen-tools/commitizen": "commitizen",
}


def _locked() -> dict[str, str]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {package["name"]: package["version"] for package in lock["package"]}


def test_pre_commit_revs_match_the_lock() -> None:
    text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    revs = dict(re.findall(r"repo: https://github\.com/(\S+)\n\s+rev: v(\S+)", text))
    locked = _locked()
    for repo, package in HOOK_PACKAGES.items():
        assert revs[repo] == locked[package], f"{repo} {revs[repo]} != {package}"


def test_ci_commitizen_pin_matches_the_lock() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    match = re.search(r"pip install commitizen==(\S+)", text)
    assert match is not None, "ci.yml no longer pins commitizen"
    assert match.group(1) == _locked()["commitizen"]
