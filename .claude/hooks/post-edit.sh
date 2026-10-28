#!/usr/bin/env bash
# PostToolUse hook for Claude's Edit and Write. Two steps, in this order, on the
# one edited file (Claude Code runs the hooks of one matcher in parallel, and
# the ASCII check must not read a file ruff is rewriting):
#
# 1. ruff, as the pre-commit ruff hooks run it: `check --fix` and then `format`
#    on Python, `format` on Markdown (its code blocks). --force-exclude keeps
#    ruff off the files its config excludes (Spec Kit's generated files).
# 2. pre-commit's own no-non-ascii hook, so a non-ASCII byte is reported at the
#    edit instead of at `git commit`; the rule - file types, exemptions,
#    pattern - lives only in .pre-commit-config.yaml. The report goes to the
#    user (systemMessage) and to Claude (additionalContext: Claude never sees a
#    systemMessage or the stderr of a hook that exits 0).
#
# uv runs --offline --no-sync, so a hook never downloads or installs anything:
# without a synced environment it does nothing, and pre-commit at commit
# (`uv run pre-commit install`) and CI still apply. pre-commit loads every repo
# its config names, so on a cold pre-commit cache the first check clones them
# (a few seconds, once); offline it stays silent until they are cached. The
# hook reports and never blocks: it always exits 0.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"
file="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null)"
# Claude Code on Windows passes native paths; compare them with forward slashes.
root="${root//\\//}"
file="${file//\\//}"

[ -n "$file" ] || exit 0
[ -f "$file" ] || exit 0
case "$file" in
  "$root"/*) ;;
  *) exit 0 ;;
esac
command -v uv >/dev/null 2>&1 || exit 0
cd "$root" || exit 0
rel="${file#"$root"/}"
run=(uv run --offline --no-sync)

case "$rel" in
  *.py) "${run[@]}" ruff check -q --fix --force-exclude -- "$rel" >/dev/null 2>&1 ;;
esac
case "$rel" in
  *.py|*.md) "${run[@]}" ruff format -q --force-exclude -- "$rel" >/dev/null 2>&1 ;;
esac

out="$("${run[@]}" pre-commit run no-non-ascii --files "$rel" 2>/dev/null)" && exit 0
# pygrep reports each offending line as "path:line:text".
hits="$(printf '%s\n' "$out" | awk -v p="$rel:" 'index($0, p) == 1 && substr($0, length(p) + 1) ~ /^[0-9]+:/' | wc -l | tr -d ' ')"
[ "${hits:-0}" -gt 0 ] || exit 0

jq -n --arg f "$rel" --arg n "$hits" '
  ($f + ": " + $n + " line(s) contain non-ASCII characters. The no-non-ascii pre-commit hook rejects these - rewrite them in ASCII.") as $msg
  | {systemMessage: $msg,
     hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $msg}}'
exit 0
