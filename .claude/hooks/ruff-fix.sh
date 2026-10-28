#!/usr/bin/env bash
# PostToolUse hook: keep every Python file Claude edits ruff-clean, so the diff
# that reaches `git commit` already matches what the pre-commit hooks (and CI)
# would produce. Reads the hook payload on stdin; always exits 0 so a missing
# toolchain never blocks an edit.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"
file="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null)"
# Claude Code on Windows passes native paths; compare them with forward slashes.
root="${root//\\//}"
file="${file//\\//}"

[ -n "$file" ] || exit 0
[ -f "$file" ] || exit 0
# Python is fixed and formatted; Markdown only formatted (ruff formats its code
# blocks), as the pre-commit ruff hooks do.
case "$file" in
  *.py|*.md) ;;
  *) exit 0 ;;
esac
# Only touch files inside this checkout.
case "$file" in
  "$root"/*) ;;
  *) exit 0 ;;
esac
command -v uv >/dev/null 2>&1 || exit 0

cd "$root" || exit 0
# --no-sync: run the ruff already installed; never sync the environment (not
# even from the cache) inside a hook. --offline: never download anything.
# Fix first, then format, as pre-commit does: a fix can change the layout.
# --force-exclude keeps ruff off the files its config excludes (Spec Kit's).
case "$file" in
  *.py) uv run --offline --no-sync ruff check -q --fix --force-exclude -- "$file" >/dev/null 2>&1 ;;
esac
uv run --offline --no-sync ruff format -q --force-exclude -- "$file" >/dev/null 2>&1
exit 0
