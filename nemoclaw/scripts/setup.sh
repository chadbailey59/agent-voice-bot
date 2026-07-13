#!/usr/bin/env bash
set -euo pipefail

sandbox="${NEMOCLAW_SANDBOX_NAME:-nc}"
model="${NEMOCLAW_MODEL:-nemotron-3-nano:30b-partial20}"
dashboard_port="${NEMOCLAW_DASHBOARD_PORT:-18790}"
endpoint="${NEMOCLAW_ENDPOINT_URL:-http://127.0.0.1:11434/v1}"

export NEMOCLAW_AGENT=openclaw
export NEMOCLAW_PROVIDER=custom
export NEMOCLAW_MODEL="$model"
export NEMOCLAW_ENDPOINT_URL="$endpoint"
export COMPATIBLE_API_KEY="${COMPATIBLE_API_KEY:-local-ollama}"
export NEMOCLAW_CONTEXT_WINDOW="${NEMOCLAW_CONTEXT_WINDOW:-16384}"
export NEMOCLAW_MAX_TOKENS="${NEMOCLAW_MAX_TOKENS:-4096}"
export NEMOCLAW_SANDBOX_NAME="$sandbox"
export NEMOCLAW_DASHBOARD_PORT="$dashboard_port"
export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1

nemoclaw onboard \
  --fresh \
  --non-interactive \
  --yes \
  --yes-i-accept-third-party-software \
  --agent openclaw \
  --name "$sandbox" \
  --control-ui-port "$dashboard_port"

# The loopback-compatible endpoint lets onboarding validate without rewriting
# the Ollama systemd unit. Runtime traffic must use the existing authenticated
# host proxy, whose provider was created by the local NemoHermes profile.
if openshell provider get ollama-local >/dev/null 2>&1; then
  nemoclaw inference set \
    --provider ollama-local \
    --model "$model" \
    --sandbox "$sandbox" \
    --no-verify
  nemoclaw "$sandbox" recover
else
  echo "warning: provider 'ollama-local' is unavailable; runtime inference may not reach loopback Ollama" >&2
fi
