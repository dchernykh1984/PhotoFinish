#!/usr/bin/env bash
# PostToolUse hook: run pre-commit's own no-non-ascii hook on the file Claude
# just edited, so a non-ASCII byte is reported at the edit instead of at
# `git commit`. The author writes in Russian, so this is the easiest rule in the
# repo to trip. The rule itself - file types, exemptions, pattern - lives only in
# .pre-commit-config.yaml. Reports to the user (systemMessage) and to Claude
# (additionalContext; Claude never sees a systemMessage or the stderr of a hook
# that exits 0). Never blocks, and stays silent when the project environment is
# not synced: the commit-time gate still applies.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"
file="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null)"

[ -n "$file" ] || exit 0
[ -f "$file" ] || exit 0
case "$file" in
  "$root"/*) ;;
  *) exit 0 ;;
esac
command -v uv >/dev/null 2>&1 || exit 0
cd "$root" || exit 0

rel="${file#"$root"/}"
out="$(uv run --offline --no-sync pre-commit run no-non-ascii --files "$rel" 2>/dev/null)" && exit 0
# pygrep reports each offending line as "path:line:text".
hits="$(printf '%s\n' "$out" | awk -v p="$rel:" 'index($0, p) == 1 && substr($0, length(p) + 1) ~ /^[0-9]+:/' | wc -l | tr -d ' ')"
[ "${hits:-0}" -gt 0 ] || exit 0

jq -n --arg f "$rel" --arg n "$hits" '
  ($f + ": " + $n + " line(s) contain non-ASCII characters. The no-non-ascii pre-commit hook rejects these - rewrite them in ASCII.") as $msg
  | {systemMessage: $msg,
     hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $msg}}'
exit 0
