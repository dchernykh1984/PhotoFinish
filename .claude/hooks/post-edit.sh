#!/usr/bin/env bash
# PostToolUse entry point. Claude Code runs the hooks of one matcher in
# parallel, and the ASCII check must not read a file while ruff rewrites it, so
# the two steps run here, in order, on the same payload.
set -uo pipefail

dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
payload="$(cat)"
printf '%s' "$payload" | bash "$dir/ruff-fix.sh"
printf '%s' "$payload" | bash "$dir/no-non-ascii.sh"
