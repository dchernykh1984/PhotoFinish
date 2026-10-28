#!/usr/bin/env bash
# PostToolUse hook: warn as soon as a non-ASCII character lands in a file the
# `no-non-ascii` pre-commit hook guards, instead of at `git commit` time. The
# author writes in Russian, so this is the easiest rule in the repo to trip.
# Only reports; never blocks.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"
file="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null)"

[ -n "$file" ] || exit 0
[ -f "$file" ] || exit 0
case "$file" in
  *.py|*.md|*.yml|*.yaml|*.toml|*.json|*.sh) ;;
  *) exit 0 ;;
esac
case "$file" in
  "$root"/*) ;;
  *) exit 0 ;;
esac
# CHANGELOG.md and uv.lock are excluded from the pre-commit hook.
case "${file#"$root"/}" in
  CHANGELOG.md|uv.lock) exit 0 ;;
esac

hits="$(LC_ALL=C grep -c '[^ -~	]' "$file" 2>/dev/null || true)"
[ "${hits:-0}" -gt 0 ] || exit 0

jq -n --arg f "${file#"$root"/}" --arg n "$hits" \
  '{systemMessage: ($f + ": " + $n + " line(s) contain non-ASCII characters. The no-non-ascii pre-commit hook rejects these in .py, .md, .yml, .toml, .json and shell files - rewrite them in ASCII.")}'
exit 0
