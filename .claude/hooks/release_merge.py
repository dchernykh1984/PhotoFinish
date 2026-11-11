#!/usr/bin/env python3
"""Deny a release PR's merge that skips its pipeline: PreToolUse, Claude's Bash.

release-please pushes its PR with GITHUB_TOKEN, so the PR's runs wait for a
maintainer to approve them, and its rollup stays empty until then; an admin merge
skips both the pipeline and the approval. A release PR goes out as the
shipping-a-change skill says: its pipeline approved and green, the PR approved,
then merged. This denies `gh pr merge` of an open release PR with --admin, or
before every check on its head has passed, and a merge that names its PR through
the shell -- `$PR`, `$(...)` -- which it cannot look up. Any other command passes,
and so does a merge gh cannot look up: the merge needs gh as well.

shortcut: only `gh pr merge` is read; a merge through `gh api` or the web page is
not -- look at those too if an agent ever merges that way.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from functools import partial
from typing import Any

RELEASE_BRANCH = "release-please--"
PASSED = {"SUCCESS", "SKIPPED", "NEUTRAL"}
# gh pr merge's flags that take a value: the word after one names no PR.
VALUE_FLAGS = {
    "-A",
    "--author-email",
    "-b",
    "--body",
    "-F",
    "--body-file",
    "--match-head-commit",
    "-R",
    "--repo",
    "-t",
    "--subject",
}
# --admin, or with a value gh reads as true: Go's strconv.ParseBool.
ADMIN = {"--admin"} | {f"--admin={v}" for v in ("1", "t", "T", "true", "True", "TRUE")}
SHELL_PUNCTUATION = set("();<>|&\n")  # a new line ends a command, as ; does
SHELLS = {"sh", "bash", "zsh", "dash"}
DESCRIPTOR = re.compile(r"(?<![\w./-])\d+(?=[<>])")
FIELDS = "number,state,headRefName,statusCheckRollup"
SKILL = "see the shipping-a-change skill, Releasing"


def merges(command: str) -> list[list[str]]:
    """The arguments of each `gh pr merge` in a shell command line, whatever the
    spaces between its words, a line continuation among them."""
    # A descriptor touching its redirection -- 2>&1 -- is no word of the command:
    # the lexer would part it from the > as a word, a PR number to the merge.
    line = DESCRIPTOR.sub("", command.replace("\\\n", " "))
    lexer = shlex.shlex(line, posix=True, punctuation_chars="".join(SHELL_PUNCTUATION))
    lexer.whitespace = " \t\r"  # a new line is punctuation
    lexer.commenters = ""  # a comment would take its new line along: see _merge_args
    lexer.whitespace_split = True
    try:
        words = list(lexer)
    except ValueError:  # an unclosed quote: the shell refuses the line too
        return []
    found: list[list[str]] = []
    for at, word in enumerate(words):
        if _script(words, at):  # bash -c '...', eval '...': a command line in one word
            found += merges(word)
        if _name(word) == "gh" and words[at + 1 : at + 2] == ["pr"]:
            args = _merge_args(words[at + 2 :])
            if args is not None:
                found.append(args)
    return found


def _merge_args(rest: list[str]) -> list[str] | None:
    """The arguments of `gh pr ... merge` -- flags gh takes before `merge`, `-R`
    among them, kept with the rest; None for another subcommand."""
    before: list[str] = []
    words = iter(rest)
    for word in words:
        if word == "merge":
            break
        if not word.startswith("-") or set(word) <= SHELL_PUNCTUATION:
            return None  # another subcommand, or the command ended first
        before.append(word)
        if word in VALUE_FLAGS:
            before.append(next(words, ""))
    else:
        return None
    args = []
    for arg in words:
        # &&, ;, a new line, |, a redirection; or a comment, a word that begins with #
        if arg and (set(arg) <= SHELL_PUNCTUATION or arg.startswith("#")):
            break
        args.append(arg)
    return before + args


def _script(words: list[str], at: int) -> bool:
    """The word at ``at`` is a command line run as such: a shell's ``-c`` script or
    what ``eval`` runs -- not a message or a pattern that names a merge."""
    if at >= 1 and words[at - 1] == "eval":
        return True
    if at < 2:
        return False
    flag = words[at - 1]  # -c, or -lc and the like
    script = flag.startswith("-") and not flag.startswith("--") and "c" in flag
    return script and _name(words[at - 2]) in SHELLS


def _name(word: str) -> str:
    """A program as a command names it, its folders left out: /usr/bin/gh is gh."""
    return word.rsplit("/", 1)[-1]


def target(args: list[str]) -> list[str]:
    """`gh pr view`'s arguments for the PR a merge names: the PR and its repo."""
    pr: list[str] = []
    repo: list[str] = []
    words = iter(args)
    for word in words:
        if word in VALUE_FLAGS:
            value = next(words, "")
            if word in {"-R", "--repo"}:
                repo = ["--repo", value]
        elif word.startswith("--repo="):
            repo = ["--repo", word.removeprefix("--repo=")]
        elif word.startswith("-R") and len(word) > 2:  # -Rowner/repo
            repo = ["--repo", word.removeprefix("-R")]
        elif not word.startswith("-") and not pr:
            pr = [word]
    return pr + repo


def look_up(view: list[str], cwd: str | None) -> dict[str, Any] | None:
    """The PR's state, branch and checks, or None when gh cannot say."""
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        done = subprocess.run(  # noqa: S603
            [gh, "pr", "view", *view, "--json", FIELDS],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if done.returncode != 0:
        return None
    try:
        pr = json.loads(done.stdout)
    except ValueError:
        return None
    return pr if isinstance(pr, dict) else None


def passed(check: dict[str, Any]) -> bool:
    """A check run that finished and did not fail, or a commit status that passed."""
    if check.get("__typename") == "StatusContext":
        return check.get("state") == "SUCCESS"
    return check.get("status") == "COMPLETED" and check.get("conclusion") in PASSED


def refusal(
    args: list[str], look: Callable[[list[str]], dict[str, Any] | None]
) -> str | None:
    """Why this merge must not run, or None when it may."""
    view = target(args)
    if any("$" in word or "`" in word for word in view):  # the shell's to expand
        return (
            "This merge names its PR or repo through the shell -- a variable, a "
            "command's output -- which this hook cannot look up: name it by its "
            f"number, so a release PR's pipeline is checked first; {SKILL}."
        )
    pr = look(view)
    if not pr or pr.get("state") != "OPEN":
        return None
    if not str(pr.get("headRefName", "")).startswith(RELEASE_BRANCH):
        return None
    number = pr.get("number")
    if ADMIN & set(args):
        return (
            f"Release PR #{number} is not merged with --admin: approve its pipeline, "
            f"wait for it to go green, approve the PR (gh pr review {number} "
            f"--approve), then merge it -- {SKILL}."
        )
    checks = pr.get("statusCheckRollup") or []
    if not checks:
        return (
            f"Release PR #{number} has no checks on its head: its runs wait for "
            f"approval -- gh run rerun each run of the head commit that reports "
            f"action_required, then wait for them to pass; {SKILL}."
        )
    waiting = [
        str(check.get("name") or check.get("context") or "?")
        for check in checks
        if not passed(check)
    ]
    if waiting:
        return (
            f"Release PR #{number} is not green yet: {', '.join(waiting)}. Wait "
            f"for its pipeline to pass and fix what fails; {SKILL}."
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    look = partial(look_up, cwd=payload.get("cwd") or None)
    for args in merges(command):
        reason = refusal(args, look)
        if reason:
            decision = {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
            json.dump({"hookSpecificOutput": decision}, sys.stdout)
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
