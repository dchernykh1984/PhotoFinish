#!/usr/bin/env bash
# PostToolUse hook: keep every Python file Claude edits ruff-clean, so the diff
# that reaches `git commit` already matches what the pre-commit hooks (and CI)
# would produce. Reads the hook payload on stdin; always exits 0 so a missing
# toolchain never blocks an edit.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"
file="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null)"

[ -n "$file" ] || exit 0
[ -f "$file" ] || exit 0
case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac
# Only touch files inside this checkout.
case "$file" in
  "$root"/*) ;;
  *) exit 0 ;;
esac
command -v uv >/dev/null 2>&1 || exit 0

cd "$root" || exit 0
uv run --frozen ruff format -q -- "$file" >/dev/null 2>&1
uv run --frozen ruff check -q --fix -- "$file" >/dev/null 2>&1
exit 0
