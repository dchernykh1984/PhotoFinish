"""Exercise the release-merge hook: the merges a command makes, the PR each names
and the checks on a release PR's head."""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
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
            [[HOOK.CD, "x", "19", "--rebase", "--admin"]],
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

    def test_a_merge_named_in_a_message_or_a_pattern_is_no_merge(self) -> None:
        self.assertEqual(HOOK.merges('git commit -m "never gh pr merge --admin"'), [])
        self.assertEqual(HOOK.merges("grep 'gh pr merge' -r ."), [])
        self.assertEqual(HOOK.merges("eval 'gh pr merge 19'"), [["19"]])
        self.assertEqual(
            HOOK.merges("/bin/zsh -c 'gh pr merge 19 --admin'"), [["19", "--admin"]]
        )

    def test_gh_by_its_path_and_a_shell_s_combined_flags(self) -> None:
        self.assertEqual(
            HOOK.merges("/opt/homebrew/bin/gh pr merge 21 --admin"), [["21", "--admin"]]
        )
        self.assertEqual(
            HOOK.merges('bash -lc "gh pr merge 21 --admin"'), [["21", "--admin"]]
        )
        self.assertEqual(HOOK.merges("ls -c 'gh pr merge 21'"), [])  # no shell

    def test_a_redirection_s_descriptor_is_no_pr(self) -> None:
        self.assertEqual(HOOK.merges("gh pr merge --admin 2>&1"), [["--admin"]])
        self.assertEqual(HOOK.merges("gh pr merge 2>/dev/null"), [[]])
        self.assertEqual(HOOK.target(HOOK.merges("gh pr merge 2>/dev/null")[0]), [])

    def test_flags_before_merge_and_a_repo_written_in_one(self) -> None:
        merged = HOOK.merges("gh pr -R owner/PhotoFinish merge 21 --admin")
        self.assertEqual(merged, [["-R", "owner/PhotoFinish", "21", "--admin"]])
        self.assertEqual(HOOK.target(merged[0]), ["21", "--repo", "owner/PhotoFinish"])
        attached = HOOK.merges("gh pr merge -Rowner/repo 21")[0]
        self.assertEqual(HOOK.target(attached), ["21", "--repo", "owner/repo"])
        self.assertEqual(HOOK.merges("gh pr -R x checkout 5 && gh pr view 21"), [])

    def test_a_new_line_ends_the_merge_and_a_comment_does_not_hide_it(self) -> None:
        for command in (
            "gh pr merge --admin\ngit status",
            "gh pr merge --admin # the release\ngit status",
            "bash -c 'gh pr merge --admin\ngit status'",
        ):
            self.assertEqual(HOOK.merges(command), [["--admin"]], command)
        self.assertEqual(
            HOOK.merges('gh pr merge 21 -t "a\nb"'), [["21", "-t", "a\nb"]]
        )

    def test_a_hash_quoted_or_inside_a_word_is_no_comment(self) -> None:
        for command in ("gh pr merge '#19' --admin", 'gh pr merge "#19" --admin'):
            self.assertEqual(HOOK.merges(command), [["#19", "--admin"]], command)
        self.assertEqual(
            HOOK.merges("gh pr merge 19 -t fix#2 --admin"),
            [["19", "-t", "fix#2", "--admin"]],
        )
        self.assertEqual(HOOK.merges("# gh pr merge 19 --admin"), [])
        self.assertEqual(
            HOOK.merges("echo x # a note \\\ngh pr merge 19 --admin"),
            [["19", "--admin"]],  # a comment's backslash continues no line
        )
        self.assertEqual(
            HOOK.merges("gh pr merge 19 \\# --admin"), [["19", "#", "--admin"]]
        )

    def test_a_pr_from_xargs_and_a_repo_from_gh_repo(self) -> None:
        piped = HOOK.merges("gh pr list -q .[0].number | xargs gh pr merge --admin")
        self.assertEqual(piped, [["$(xargs)", "--admin"]])  # denied, as $PR is
        for command in (
            "GH_REPO=o/r gh pr merge 19",
            "export GH_REPO=o/r; gh pr merge 19",
        ):
            self.assertEqual(HOOK.merges(command), [["--repo", "o/r", "19"]], command)
        self.assertEqual(
            HOOK.merges("GH_REPO=o/r gh pr list; gh pr merge 19"), [["19"]]
        )
        given = HOOK.merges("GH_REPO=o/r gh pr merge 19 -R x/y")[0]
        self.assertEqual(HOOK.target(given), ["19", "--repo", "x/y"])  # its flag first

    def test_a_merge_run_for_its_output(self) -> None:
        for command in (
            "echo `gh pr merge 5 --admin`",
            'out="$(gh pr merge 5 --admin)"',
            "x=$(gh pr merge 5 --admin)",
            'echo "$(echo $(gh pr merge 5 --admin))"',
        ):
            self.assertEqual(HOOK.merges(command), [["5", "--admin"]], command)
        self.assertEqual(HOOK.merges("echo '$(gh pr merge 5 --admin)'"), [])  # text
        self.assertEqual(HOOK.merges("echo \\`gh pr merge 5\\`"), [])  # escaped: text

    def test_a_script_or_an_output_s_merge_after_what_comes_before_it(self) -> None:
        for command, merged in (
            ("cd ../X && bash -c 'gh pr merge 21 --admin'", [HOOK.CD, "../X", "21"]),
            ("cd ../X && eval 'gh pr merge 21 --admin'", [HOOK.CD, "../X", "21"]),
            ('cd ../X && out="$(gh pr merge 21 --admin)"', [HOOK.CD, "../X", "21"]),
            ("cd ../X && echo `gh pr merge 21 --admin`", [HOOK.CD, "../X", "21"]),
            (
                "export GH_REPO=o/x; bash -c 'gh pr merge 21 --admin'",
                ["--repo", "o/x", "21"],
            ),
        ):
            self.assertEqual(HOOK.merges(command), [[*merged, "--admin"]], command)

    def test_a_cd_s_options_are_no_folder_and_cd_dash_is_the_shell_s(self) -> None:
        for command, folder in (
            ("cd -P /srv && gh pr merge 21", "/srv"),
            ("cd -L -- /srv && gh pr merge 21", "/srv"),
            ("cd -- && gh pr merge 21", str(Path.home())),
        ):
            self.assertEqual(HOOK.where(HOOK.merges(command)[0], "/repo")[0], folder)
        back = HOOK.where(HOOK.merges("cd - && gh pr merge 21 --admin")[0], "/repo")
        self.assertIn(
            "through the shell", HOOK.refusal(back[1], lambda v: None, back[0])
        )

    def test_a_merge_after_a_cd_runs_in_its_folder(self) -> None:
        merged = HOOK.merges("cd ../Other; git pull && cd sub && gh pr merge 12")
        self.assertEqual(merged, [[HOOK.CD, "../Other", HOOK.CD, "sub", "12"]])
        self.assertEqual(HOOK.where(merged[0], "/x/repo"), ("/x/Other/sub", ["12"]))
        back = HOOK.merges("cd .. && cd PhotoFinish && gh pr merge 21")[0]
        self.assertEqual(HOOK.where(back, "/x/repo")[0], "/x/PhotoFinish")
        for command, folder in (
            (
                "(cd /srv && ls); gh pr merge 21",
                "/repo",
            ),  # the subshell's cd stays there
            ("(cd /srv && gh pr merge 21)", "/srv"),
            ("x=$(cd /srv && gh pr merge 21)", "/srv"),
        ):
            merge = HOOK.merges(command)
            self.assertEqual(len(merge), 1, command)
            self.assertEqual(HOOK.where(merge[0], "/repo")[0], folder, command)
        self.assertEqual(HOOK.where(["12"], "/repo"), ("/repo", ["12"]))
        home = HOOK.where(HOOK.merges("cd && gh pr merge 12")[0], "/repo")[0]
        self.assertEqual(home, str(Path.home()))
        absolute = HOOK.merges("cd /x/PhotoFinish && gh pr merge 12")[0]
        self.assertEqual(HOOK.where(absolute, "/repo")[0], "/x/PhotoFinish")

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
    def refusal(self, args: list[str], found: dict | None, folder: str = "") -> Any:
        return HOOK.refusal(args, lambda view: found, folder)

    def test_an_admin_merge_of_a_release_pr_is_denied_even_when_green(self) -> None:
        reason = self.refusal(["19", "--rebase", "--admin"], pr([check("tests")]))
        self.assertIn("--admin", reason)

    def test_admin_written_with_any_value_gh_reads_as_true(self) -> None:
        green = pr([check("tests")])
        for admin in ("--admin=1", "--admin=t", "--admin=True", "--admin=TRUE"):
            self.assertIn("--admin", self.refusal(["19", admin], green), admin)
        self.assertIsNone(self.refusal(["19", "--admin=false"], green))

    def test_a_pr_named_through_the_shell_is_denied(self) -> None:
        for args in (["$PR", "--admin"], ["$(gh"], ["`gh", "pr"], ["9", "-R", "$R"]):
            self.assertIn("through the shell", self.refusal(args, None), args)
        merged = HOOK.merges('gh pr merge "$(gh pr list -q .[0].number)" --admin')
        self.assertIn("through the shell", self.refusal(merged[0], None))

    def test_a_pr_given_by_xargs_is_denied(self) -> None:
        merged = HOOK.merges("echo 19 | xargs gh pr merge --admin")
        self.assertIn("through the shell", self.refusal(merged[0], None))

    def test_a_run_still_waiting_for_approval_holds_a_green_release_pr(self) -> None:
        green = pr([check("tests")]) | {"headRefOid": "abc"}
        approved = {"name": "CI", "status": "completed", "conclusion": "success"}
        waiting = {"name": "pr-build", "status": "completed"}
        waiting["conclusion"] = "action_required"
        asked: list[tuple[str, list[str]]] = []

        def runs(sha: str, repo: list[str]) -> list[dict]:
            asked.append((sha, repo))
            return [approved, waiting]

        reason = HOOK.refusal(["19", "-R", "o/r"], lambda view: green, "", runs)
        self.assertIn("its runs pr-build wait", reason)
        self.assertEqual(asked, [("abc", ["--repo", "o/r"])])
        both = [approved, approved | {"name": "pr-build"}]
        self.assertIsNone(HOOK.refusal(["19"], lambda view: green, "", lambda *a: both))
        unknown = HOOK.refusal(["19"], lambda view: green, "", lambda *a: None)
        self.assertIsNone(unknown)  # gh cannot say: the checks decide

    def test_a_run_cancelled_and_run_again_since_holds_nothing(self) -> None:
        green = pr([check("tests")]) | {"headRefOid": "abc"}
        old = {"name": "CI", "status": "completed", "conclusion": "cancelled"}
        again = {"name": "CI", "status": "completed", "conclusion": "success"}
        runs = [old | {"createdAt": "2026-11-11T06:00:00Z"}]
        runs += [again | {"createdAt": "2026-11-11T06:05:00Z"}]
        self.assertIsNone(HOOK.refusal(["19"], lambda view: green, "", lambda *a: runs))
        last = HOOK.refusal(["19"], lambda view: green, "", lambda *a: runs[::-1][1:])
        self.assertIn("its runs CI", last)  # cancelled, and the newest

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
            patch.object(HOOK, "look_up_runs", return_value=None),
            patch("sys.stdin", io.StringIO(json.dumps(payload))),
            patch("sys.stdout", out),
        ):
            self.assertEqual(HOOK.main(), 0)
        for call in look_up.call_args_list:
            self.assertEqual(call.kwargs["cwd"], "/repo")
            self.assertLessEqual(call.kwargs["timeout"], HOOK.LOOKUP_S)
        return out.getvalue()

    def test_a_denied_merge_prints_the_decision(self) -> None:
        decision = json.loads(self.run_hook("gh pr merge 19 --admin", pr([])))
        output = decision["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("#19", output["permissionDecisionReason"])

    def test_the_pr_is_looked_up_where_a_cd_before_the_merge_went(self) -> None:
        payload = {
            "cwd": "/repo",
            "tool_input": {"command": "cd sub && gh pr merge 19"},
        }
        with (
            patch.object(HOOK, "look_up", return_value=None) as look_up,
            patch("sys.stdin", io.StringIO(json.dumps(payload))),
            patch("sys.stdout", io.StringIO()),
        ):
            HOOK.main()
        self.assertEqual(look_up.call_args.kwargs["cwd"], "/repo/sub")
        cd_home = HOOK.refusal(["19"], lambda view: None, "/repo/$HOME")
        self.assertIn("through the shell", cd_home)

    def test_merges_past_the_hook_s_time_are_denied(self) -> None:
        clock = iter([0.0, 10.0, 100.0]).__next__  # the second asked past the budget
        with patch.object(HOOK, "time", SimpleNamespace(monotonic=clock)):
            out = self.run_hook("gh pr merge 18 && gh pr merge 19", pr([], "feat/x"))
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("too long to check", reason)

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
