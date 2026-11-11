#!/usr/bin/env bash
# PreToolUse hook for Claude's Bash. A command that merges a pull request goes to
# release_merge.py, which denies merging a release PR with --admin or before its
# pipeline is green (the shipping-a-change skill has the steps); any other command
# passes at once, with no Python started. It denies only by the answer it prints:
# without uv, or when the check itself fails, the command runs.
set -uo pipefail

payload="$(cat)"
# A loose sieve -- any spaces, a line continuation: the Python reads the words.
case "$payload" in
  *gh*merge*) ;;
  *) exit 0 ;;
esac
command -v uv >/dev/null 2>&1 || exit 0
cd "${CLAUDE_PROJECT_DIR:-$PWD}" || exit 0
printf '%s' "$payload" |
  uv run --offline --no-sync python .claude/hooks/release_merge.py 2>/dev/null
exit 0
