"""Exercise Codex patch payloads, repository boundaries and the pre-commit call."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("post_edit.py")
SPEC = importlib.util.spec_from_file_location("post_edit", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load hook")
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)

FAILED = "no non-ASCII characters....Failed\n- hook id: no-non-ascii\n\n"


def completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class PostEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.checked = self.root / "source.md"
        self.checked.write_text("plain ASCII\n", encoding="utf-8")

    def payload(self, command: str, **extra: str) -> dict:
        return {"cwd": str(self.root), "tool_input": {"command": command}, **extra}

    def test_multi_file_patch_resolves_every_edited_file(self) -> None:
        other = self.root / "other.md"
        other.write_text("x", encoding="utf-8")
        paths = HOOK.edited_paths(
            self.payload("*** Update File: source.md\n*** Add File: other.md\n"),
            self.root,
        )
        self.assertEqual(paths, [self.checked, other])

    def test_crlf_patch_resolves_every_edited_and_moved_file(self) -> None:
        other = self.root / "other.md"
        moved = self.root / "moved.md"
        for path in [other, moved]:
            path.write_text("x", encoding="utf-8")
        paths = HOOK.edited_paths(
            self.payload(
                "*** Begin Patch\r\n"
                "*** Update File: source.md\r\n"
                "*** Add File: other.md\r\n"
                "*** Update File: old.md\r\n"
                "*** Move to: moved.md\r\n"
                "*** End Patch\r\n"
            ),
            self.root,
        )
        self.assertEqual(paths, [self.checked, other, moved])

    def test_move_checks_the_destination(self) -> None:
        paths = HOOK.edited_paths(
            self.payload("*** Update File: missing.md\n*** Move to: source.md\n"),
            self.root,
        )
        self.assertEqual(paths, [self.checked])

    def test_delete_and_missing_files_are_ignored(self) -> None:
        paths = HOOK.edited_paths(
            self.payload("*** Delete File: source.md\n*** Add File: missing.md\n"),
            self.root,
        )
        self.assertEqual(paths, [])

    def test_subdirectory_payload_resolves_relative_files(self) -> None:
        subdir = self.root / "nested"
        subdir.mkdir()
        paths = HOOK.edited_paths(
            self.payload("*** Update File: ../source.md\n", cwd=str(subdir)),
            self.root,
        )
        self.assertEqual(paths, [self.checked])

    def test_paths_outside_the_repository_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.md"
            external.write_text(chr(0x416), encoding="utf-8")
            paths = HOOK.edited_paths(
                self.payload(f"*** Add File: {external}\n"), self.root
            )
            self.assertEqual(paths, [])

    def test_symlink_to_outside_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.md"
            external.write_text(chr(0x416), encoding="utf-8")
            link = self.root / "link.md"
            try:
                link.symlink_to(external)
            except OSError:
                self.skipTest("Symlinks are unavailable")
            self.assertEqual(
                HOOK.edited_paths(
                    self.payload("*** Update File: link.md\n"), self.root
                ),
                [],
            )

    def test_legacy_file_path_is_supported_and_deduplicated(self) -> None:
        payload = self.payload("*** Update File: source.md\n")
        payload["tool_input"]["file_path"] = str(self.checked)
        self.assertEqual(HOOK.edited_paths(payload, self.root), [self.checked])

    def test_non_object_tool_input_is_ignored(self) -> None:
        self.assertEqual(HOOK.edited_paths({"tool_input": "text"}, self.root), [])

    def test_violations_ask_pre_commit_for_its_own_rule(self) -> None:
        other = self.root / "nested/other.md"
        other.parent.mkdir()
        other.write_text("x", encoding="utf-8")
        with (
            patch.object(HOOK.shutil, "which", return_value="uv"),
            patch.object(HOOK.subprocess, "run", return_value=completed(0)) as run,
        ):
            self.assertEqual(HOOK.violations([self.checked, other], self.root), [])
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["uv", "run", "--offline", "--no-sync"])
        self.assertEqual(
            command[4:],
            [
                "pre-commit",
                "run",
                "no-non-ascii",
                "--files",
                "source.md",
                "nested/other.md",
            ],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], self.root)

    def test_violations_report_the_files_pre_commit_names(self) -> None:
        other = self.root / "other.md"
        clean = self.root / "clean.md"
        for path in [other, clean]:
            path.write_text("x", encoding="utf-8")
        output = FAILED + "source.md:3:caf\nother.md:1:x\nother.md:7:y\n"
        with (
            patch.object(HOOK.shutil, "which", return_value="uv"),
            patch.object(HOOK.subprocess, "run", return_value=completed(1, output)),
        ):
            self.assertEqual(
                HOOK.violations([self.checked, other, clean], self.root),
                ["source.md", "other.md"],
            )

    def test_violations_stay_quiet_when_pre_commit_cannot_run(self) -> None:
        with patch.object(HOOK.shutil, "which", return_value=None):
            self.assertEqual(HOOK.violations([self.checked], self.root), [])
        with (
            patch.object(HOOK.shutil, "which", return_value="uv"),
            patch.object(HOOK.subprocess, "run", side_effect=OSError("no uv")),
        ):
            self.assertEqual(HOOK.violations([self.checked], self.root), [])
        missing_env = "error: Failed to spawn: `pre-commit`\n"
        with (
            patch.object(HOOK.shutil, "which", return_value="uv"),
            patch.object(
                HOOK.subprocess, "run", return_value=completed(2, missing_env)
            ),
        ):
            self.assertEqual(HOOK.violations([self.checked], self.root), [])

    def test_formatter_handles_every_python_file_from_project_root(self) -> None:
        first = self.root / "first.py"
        second = self.root / "second.py"
        with (
            patch.object(HOOK.shutil, "which", return_value="uv"),
            patch.object(HOOK.subprocess, "run") as run,
        ):
            run.return_value.returncode = 0
            HOOK.format_python([first, self.checked, second], self.root)
        self.assertEqual(run.call_count, 2)
        actions = [call.args[0][5] for call in run.call_args_list]
        self.assertEqual(actions, ["check", "format"])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.root)
            self.assertEqual(call.args[0][-2:], [str(first), str(second)])
            self.assertIn("--offline", call.args[0])
            self.assertIn("--no-sync", call.args[0])

    def test_formatter_ignores_other_types_and_missing_toolchain(self) -> None:
        with (
            patch.object(HOOK.shutil, "which", return_value=None),
            patch.object(HOOK.subprocess, "run") as run,
        ):
            HOOK.format_python([self.root / "code.py"], self.root)
            HOOK.format_python([self.checked], self.root)
        run.assert_not_called()

    def test_formatter_timeout_still_runs_the_ascii_check(self) -> None:
        code = self.root / "code.py"
        code.write_text("x = 1\n", encoding="utf-8")
        payload = self.payload("*** Update File: code.py\n")
        outcomes = [
            subprocess.TimeoutExpired("uv", 25),
            completed(1, FAILED + "code.py:1:x\n"),
        ]
        with (
            patch.object(HOOK, "ROOT", self.root),
            patch.object(HOOK.shutil, "which", return_value="uv"),
            patch.object(HOOK.subprocess, "run", side_effect=outcomes),
            patch.object(HOOK.sys, "stdin", io.StringIO(json.dumps(payload))),
            patch.object(HOOK.sys, "stderr", io.StringIO()) as stderr,
        ):
            self.assertEqual(HOOK.main(), 2)
        self.assertIn("code.py", stderr.getvalue())

    @unittest.skipIf(os.name == "nt", "the fake uv is a POSIX shell script")
    def test_cli_reports_bytes_from_a_different_working_directory(self) -> None:
        folder = self.root / ".codex/hooks"
        folder.mkdir(parents=True)
        script = folder / "post_edit.py"
        script.write_bytes(SCRIPT.read_bytes())
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake_uv = bin_dir / "uv"
        fake_uv.write_text(
            "#!/bin/sh\nprintf 'source.md:1:caf\\n'\nexit 1\n", encoding="utf-8"
        )
        fake_uv.chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(script)],
            input=json.dumps(self.payload("*** Update File: source.md\n")),
            text=True,
            capture_output=True,
            cwd=folder,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("source.md", result.stderr)

    def test_cli_ignores_invalid_json(self) -> None:
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(SCRIPT)],
            input="not JSON",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
