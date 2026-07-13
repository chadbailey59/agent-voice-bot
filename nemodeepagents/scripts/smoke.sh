#!/usr/bin/env bash
set -euo pipefail

sandbox="${NEMOCLAW_SANDBOX_NAME:-nd}"
nemoclaw "$sandbox" exec --no-tty --timeout 300 -- \
  dcode -n "Reply with exactly: DEEPAGENTS_VOICE_READY"
