"""Exercise the release-merge hook: the merges a command makes, the PR each names
and the checks on a release PR's head."""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("release_merge.py")
SPEC = importlib.util.spec_from_file_location("release_merge", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load hook")
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)

BRANCH = "release-please--branches--main"
GREEN = {"__typename": "CheckRun", "name": "tests", "status": "COMPLETED"}


def check(name: str, status: str = "COMPLETED", conclusion: str = "SUCCESS") -> dict:
    return {**GREEN, "name": name, "status": status, "conclusion": conclusion}


def pr(checks: list[dict], branch: str = BRANCH, state: str = "OPEN") -> dict:
    return {
        "number": 19,
        "state": state,
        "headRefName": branch,
        "statusCheckRollup": checks,
    }


class MergesTests(unittest.TestCase):
    def test_a_merge_in_a_chain_ends_at_the_next_command(self) -> None:
        self.assertEqual(
            HOOK.merges("cd x && gh pr merge 19 --rebase --admin && echo ok"),
            [["19", "--rebase", "--admin"]],
        )

    def test_a_merge_in_a_quoted_script(self) -> None:
        self.assertEqual(
            HOOK.merges("bash -c 'gh pr merge 19 --admin'"), [["19", "--admin"]]
        )

    def test_a_merge_ends_at_a_redirection(self) -> None:
        self.assertEqual(HOOK.merges("gh pr merge 19 > out.txt"), [["19"]])

    def test_an_empty_value_does_not_end_the_merge(self) -> None:
        self.assertEqual(
            HOOK.merges('gh pr merge 19 --body "" --admin'),
            [["19", "--body", "", "--admin"]],
        )

    def test_a_merge_written_with_other_spaces_or_over_two_lines(self) -> None:
        self.assertEqual(HOOK.merges("gh pr  merge 19\t--admin"), [["19", "--admin"]])
        self.assertEqual(
            HOOK.merges("gh pr \\\n merge 19 --admin"), [["19", "--admin"]]
        )

    def test_no_merge(self) -> None:
        self.assertEqual(HOOK.merges("gh pr view 19 && gh run list"), [])
        self.assertEqual(HOOK.merges("echo 'unclosed"), [])


class TargetTests(unittest.TestCase):
    def test_the_pr_is_the_first_word_no_flag_takes(self) -> None:
        self.assertEqual(
            HOOK.target(["--match-head-commit", "c19d", "--rebase", "19"]), ["19"]
        )

    def test_the_repo_goes_along(self) -> None:
        url = "https://github.com/o/r/pull/19"
        self.assertEqual(
            HOOK.target(["--subject", "release 19", "-R", "o/r", url]),
            [url, "--repo", "o/r"],
        )
        self.assertEqual(HOOK.target(["19", "--repo=o/r"]), ["19", "--repo", "o/r"])

    def test_no_pr_named_is_the_current_branch(self) -> None:
        self.assertEqual(HOOK.target(["--rebase"]), [])


class RefusalTests(unittest.TestCase):
    def refusal(self, args: list[str], found: dict | None) -> Any:
        return HOOK.refusal(args, lambda view: found)

    def test_an_admin_merge_of_a_release_pr_is_denied_even_when_green(self) -> None:
        reason = self.refusal(["19", "--rebase", "--admin"], pr([check("tests")]))
        self.assertIn("--admin", reason)

    def test_a_release_pr_with_no_checks_waits_for_their_approval(self) -> None:
        reason = self.refusal(["19", "--rebase"], pr([]))
        self.assertIn("action_required", reason)

    def test_a_release_pr_with_a_check_running_or_failed_is_denied(self) -> None:
        checks = [
            check("tests"),
            check("android", status="IN_PROGRESS", conclusion=""),
            check("audit", conclusion="FAILURE"),
        ]
        reason = self.refusal(["19", "--rebase"], pr(checks))
        self.assertIn("android, audit", reason)

    def test_a_green_release_pr_is_merged(self) -> None:
        checks = [
            check("tests"),
            check("build / verify", conclusion="SKIPPED"),
            {"__typename": "StatusContext", "context": "ci/x", "state": "SUCCESS"},
        ]
        self.assertIsNone(self.refusal(["19", "--rebase"], pr(checks)))

    def test_a_failed_commit_status_is_denied(self) -> None:
        status = {"__typename": "StatusContext", "context": "ci/x", "state": "FAILURE"}
        self.assertIn("ci/x", self.refusal(["19"], pr([status])))

    def test_other_prs_and_unknown_ones_pass(self) -> None:
        self.assertIsNone(self.refusal(["18", "--admin"], pr([], branch="feat/x")))
        self.assertIsNone(self.refusal(["19", "--admin"], pr([], state="MERGED")))
        self.assertIsNone(self.refusal(["19", "--admin"], None))

    def test_the_pr_is_looked_up_as_the_merge_names_it(self) -> None:
        asked: list[list[str]] = []

        def look(view: list[str]) -> None:
            asked.append(view)

        HOOK.refusal(["--rebase", "19", "-R", "o/r"], look)
        self.assertEqual(asked, [["19", "--repo", "o/r"]])


class MainTests(unittest.TestCase):
    def run_hook(self, command: str, found: dict | None) -> str:
        payload = {"cwd": "/repo", "tool_input": {"command": command}}
        out = io.StringIO()
        with (
            patch.object(HOOK, "look_up", return_value=found) as look_up,
            patch("sys.stdin", io.StringIO(json.dumps(payload))),
            patch("sys.stdout", out),
        ):
            self.assertEqual(HOOK.main(), 0)
        for call in look_up.call_args_list:
            self.assertEqual(call.kwargs, {"cwd": "/repo"})
        return out.getvalue()

    def test_a_denied_merge_prints_the_decision(self) -> None:
        decision = json.loads(self.run_hook("gh pr merge 19 --admin", pr([])))
        output = decision["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("#19", output["permissionDecisionReason"])

    def test_an_allowed_command_prints_nothing(self) -> None:
        self.assertEqual(self.run_hook("gh pr merge 19 --rebase", pr([check("a")])), "")
        self.assertEqual(self.run_hook("git status", None), "")

    def test_a_payload_that_is_not_a_command_passes(self) -> None:
        for raw in ("not json", "[]", '{"tool_input": {"file_path": "x"}}'):
            with (
                patch("sys.stdin", io.StringIO(raw)),
                patch("sys.stdout", io.StringIO()) as out,
            ):
                self.assertEqual(HOOK.main(), 0)
            self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
