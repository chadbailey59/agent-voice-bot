#!/usr/bin/env bash
set -euo pipefail

sandbox="${NEMOCLAW_SANDBOX_NAME:-nc}"
nemoclaw "$sandbox" exec --no-tty --timeout 120 -- \
  openclaw agent --agent main --session-id voice-smoke -m \
  "Reply with exactly: NEMOCLAW_VOICE_READY"
