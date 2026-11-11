#!/usr/bin/env python3
"""Deny a release PR's merge that skips its pipeline: PreToolUse, Claude's Bash.

release-please pushes its PR with GITHUB_TOKEN, so the PR's runs wait for a
maintainer to approve them, and its rollup stays empty until then; an admin merge
skips both the pipeline and the approval. A release PR goes out as the
shipping-a-change skill says: its pipeline approved and green, the PR approved,
then merged. This denies `gh pr merge` of an open release PR with --admin, or
before every check on its head has passed, and a merge that names its PR through
the shell -- `$PR`, `$(...)` -- which it cannot look up. A PR is looked up where
its merge runs, a cd before it followed. Any other command passes, and so does a
merge gh cannot look up: the merge needs gh as well.

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
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
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
WORD_START = set(" \t\n;&|()<>")  # what a word may begin after: a # there is a comment
DESCRIPTOR = re.compile(r"(?<![\w./-])\d+(?=[<>])")
FIELDS = "number,state,headRefName,headRefOid,statusCheckRollup"
RUN_FIELDS = "name,status,conclusion"
RUN_PASSED = {"success", "skipped", "neutral"}
LOOKUP_S = 20  # one PR looked up
# All of a command's merges looked up within this, inside the hook's 90 s timeout in
# .claude/settings.json: a hook cut short by it says nothing, and the merge runs.
BUDGET_S = 80
SKILL = "see the shipping-a-change skill, Releasing"
CD = "\0cd"  # a merge's arguments start with it and a folder after a cd before it


def merges(command: str) -> list[list[str]]:
    """The arguments of each `gh pr merge` in a shell command line, whatever the
    spaces between its words, a line continuation among them."""
    uncommented = _uncommented(command)
    # Run for their output: `...` and $(...), in double quotes too.
    found = [merge for inner in _substituted(uncommented) for merge in merges(inner)]
    # A descriptor touching its redirection -- 2>&1 -- is no word of the command:
    # the lexer would part it from the > as a word, a PR number to the merge.
    line = DESCRIPTOR.sub("", uncommented.replace("\\\n", " "))
    lexer = shlex.shlex(line, posix=True, punctuation_chars="".join(SHELL_PUNCTUATION))
    lexer.whitespace = " \t\r"  # a new line is punctuation
    lexer.commenters = ""  # gone already, as the shell reads them
    lexer.whitespace_split = True
    try:
        words = list(lexer)
    except ValueError:  # an unclosed quote: the shell refuses the line too
        return found
    for at, word in enumerate(words):
        if _script(words, at):  # bash -c '...', eval '...': a command line in one word
            found += merges(word)
        if _name(word) == "gh" and words[at + 1 : at + 2] == ["pr"]:
            args = _merge_args(words[at + 2 :])
            if args is not None:
                found.append(_given(words[:at]) + args)
    return [list(merge) for merge in dict.fromkeys(map(tuple, found))]  # each once


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
        if arg and set(arg) <= SHELL_PUNCTUATION:  # &&, ;, a new line, |, a redirection
            break
        args.append(arg)
    return before + args


def _given(before: list[str]) -> list[str]:
    """What a merge takes from outside its words: the folder a cd before it moved
    to, the PR xargs adds from its input, the shell's to fill as $PR is, and a
    GH_REPO set for gh or exported before, as its --repo."""
    stdin: list[str] = []
    repo: list[str] = []
    own = True  # gh's own command: the words back to the separator before it
    for at in range(len(before) - 1, -1, -1):
        word = before[at]
        if word and set(word) <= SHELL_PUNCTUATION:
            own = False
        elif own and _name(word) == "xargs":
            stdin = ["$(xargs)"]
        elif word.startswith("GH_REPO=") and not repo:
            if own or before[at - 1 : at] == ["export"]:
                repo = ["--repo", word.removeprefix("GH_REPO=")]
    return _folder(before) + stdin + repo


def _folder(before: list[str]) -> list[str]:
    """[CD, the folder] of the last cd among the commands before; [] with none."""
    folder: list[str] = []
    begins = True  # a command begins at this word
    for at, word in enumerate(before):
        if word and set(word) <= SHELL_PUNCTUATION:
            begins = True
            continue
        if begins and word == "cd":
            after = before[at + 1 : at + 2]
            given = after and not set(after[0]) <= SHELL_PUNCTUATION
            folder = [CD, after[0] if given else "~"]
        begins = False
    return folder


def where(args: list[str], cwd: str | None) -> tuple[str | None, list[str]]:
    """The folder a merge runs in -- a cd before it, from ``cwd`` -- and its
    arguments."""
    if args[:1] != [CD]:
        return cwd, args
    return str(Path(cwd or ".") / Path(args[1]).expanduser()), args[2:]


def _substituted(command: str) -> list[str]:
    """The command lines the shell runs for their output: `...` and $(...), bare or
    in double quotes -- not in single ones, where they are text."""
    found: list[str] = []
    quote = ""
    at = 0
    while at < len(command):
        char = command[at]
        if quote == "'":
            quote = "" if char == "'" else quote
        elif char == "\\":
            at += 1  # the next is escaped
        elif char == "'" and not quote:
            quote = "'"
        elif char == '"':
            quote = "" if quote else '"'
        elif char == "`":
            end = command.find("`", at + 1)
            end = len(command) if end < 0 else end
            found.append(command[at + 1 : end])
            at = end
        elif command.startswith("$(", at):
            end = _closing(command, at + 1)
            found.append(command[at + 2 : end])
            at = end
        at += 1
    return found


def _closing(command: str, start: int) -> int:
    """Where the parenthesis opened at ``start`` closes; the end, if never."""
    depth = 0
    for at in range(start, len(command)):
        if command[at] == "(":
            depth += 1
        elif command[at] == ")":
            depth -= 1
            if depth == 0:
                return at
    return len(command)


def _uncommented(command: str) -> str:
    """The command without its comments, as the shell reads them: from a # that
    begins a word, outside quotes, to the line's end -- its new line kept, which
    ends the command, even after a backslash."""
    kept: list[str] = []
    quote = ""
    at = 0
    while at < len(command):
        char = command[at]
        if char == "\\" and quote != "'":  # escaped: neither a quote nor a comment
            kept.append(command[at : at + 2])
            at += 2
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (not kept or kept[-1][-1] in WORD_START):
            end = command.find("\n", at)
            at = len(command) if end < 0 else end
            continue
        kept.append(char)
        at += 1
    return "".join(kept)


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


def _gh(args: list[str], cwd: str | None, timeout: float) -> Any:
    """What gh prints as JSON for ``args``, or None when it cannot say."""
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        done = subprocess.run(  # noqa: S603
            [gh, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):  # fmt: skip
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return None


def look_up(
    view: list[str], cwd: str | None, timeout: float = LOOKUP_S
) -> dict[str, Any] | None:
    """The PR's state, branch, head and checks, or None when gh cannot say."""
    pr = _gh(["pr", "view", *view, "--json", FIELDS], cwd, timeout)
    return pr if isinstance(pr, dict) else None


def look_up_runs(
    sha: str, repo: list[str], cwd: str | None, timeout: float = LOOKUP_S
) -> list[dict[str, Any]] | None:
    """The workflow runs of a commit, or None when gh cannot say: a run waiting
    for approval has no check in the PR's rollup."""
    command = ["run", "list", "--commit", sha, *repo, "--json", RUN_FIELDS]
    found = _gh([*command, "--limit", "100"], cwd, timeout)
    return found if isinstance(found, list) else None


def passed(check: dict[str, Any]) -> bool:
    """A check run that finished and did not fail, or a commit status that passed."""
    if check.get("__typename") == "StatusContext":
        return check.get("state") == "SUCCESS"
    return check.get("status") == "COMPLETED" and check.get("conclusion") in PASSED


def refusal(
    args: list[str],
    look: Callable[[list[str]], dict[str, Any] | None],
    folder: str = "",
    runs: Callable[[str, list[str]], list[dict[str, Any]] | None] | None = None,
) -> str | None:
    """Why this merge, run in ``folder``, must not run, or None when it may;
    ``runs`` gives the head's workflow runs by its commit and repo."""
    view = target(args)
    if any("$" in word or "`" in word for word in [*view, folder]):  # the shell's
        return (
            "This merge names its PR, repo or folder through the shell -- a "
            "variable, a command's output -- which this hook cannot look up: name "
            f"it as it is, so a release PR's pipeline is checked first; {SKILL}."
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
    repo = view[view.index("--repo") :] if "--repo" in view else []
    held = [  # a run approved in part: those still waiting have no check yet
        str(run.get("name") or "?")
        for run in (runs(str(pr.get("headRefOid", "")), repo) if runs else None) or []
        if run.get("status") != "completed" or run.get("conclusion") not in RUN_PASSED
    ]
    if held:
        return (
            f"Release PR #{number} is not green yet: its runs {', '.join(held)} wait "
            f"for approval or have not passed -- gh run rerun each one that reports "
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
    cwd = payload.get("cwd") or None
    deadline = time.monotonic() + BUDGET_S
    for merge in merges(command):
        here, args = where(merge, cwd)
        left = deadline - time.monotonic()
        each = min(LOOKUP_S, left / 2)  # the PR, then its head's runs
        look = partial(look_up, cwd=here, timeout=each)
        runs = partial(look_up_runs, cwd=here, timeout=each)
        reason = (
            refusal(args, look, here or "", runs)
            if left >= 1
            else f"These merges take too long to check: one at a time; {SKILL}."
        )
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
