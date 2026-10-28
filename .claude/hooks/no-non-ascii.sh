#!/usr/bin/env bash
# PostToolUse hook: warn as soon as a non-ASCII character lands in a file the
# `no-non-ascii` pre-commit hook guards, instead of at `git commit` time. The
# author writes in Russian, so this is the easiest rule in the repo to trip.
# Reports to the user (systemMessage) and to Claude (additionalContext; Claude
# never sees a systemMessage or the stderr of a hook that exits 0). Never blocks.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"
file="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null)"

[ -n "$file" ] || exit 0
[ -f "$file" ] || exit 0
case "$file" in
  "$root"/*) ;;
  *) exit 0 ;;
esac
# The checked file types and the exemptions (CHANGELOG.md, uv.lock, Spec Kit's
# generated files) come from the file the Codex hook reads;
# tests/test_ascii_rules.py keeps it equal to the pre-commit rule.
checks="$root/.codex/hooks/checks.json"
jq -e --arg p "${file#"$root"/}" \
  '. as $c | ($p | test($c.files)) and (($p | test($c.exclude)) | not)' \
  "$checks" >/dev/null 2>&1 || exit 0

# Bytes above 0x7F only, as pre-commit counts them: CR and other control
# characters are ASCII and are not reported.
hits="$(LC_ALL=C grep -c $'[\x80-\xff]' "$file" 2>/dev/null || true)"
[ "${hits:-0}" -gt 0 ] || exit 0

jq -n --arg f "${file#"$root"/}" --arg n "$hits" '
  ($f + ": " + $n + " line(s) contain non-ASCII characters. The no-non-ascii pre-commit hook rejects these in .py, .md, .yml, .toml, .json and shell files - rewrite them in ASCII.") as $msg
  | {systemMessage: $msg,
     hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $msg}}'
exit 0
