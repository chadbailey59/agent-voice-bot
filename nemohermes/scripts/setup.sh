#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"

sandbox="${NEMOCLAW_SANDBOX_NAME:-nh}"
model="${NEMOCLAW_MODEL:-gpt-5.4}"

# The key is a secret and is never checked in. Prefer the exported value, then
# fall back to bot/.env for local work.
if [[ -z "${OPENAI_API_KEY:-}" && -f "$repo_root/bot/.env" ]]; then
  OPENAI_API_KEY="$(sed -n 's/^OPENAI_API_KEY=//p' "$repo_root/bot/.env" | head -1)"
fi
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "error: OPENAI_API_KEY is required; export it or set it in bot/.env" >&2
  exit 1
fi
export OPENAI_API_KEY

export NEMOCLAW_AGENT=hermes
export NEMOCLAW_PROVIDER=openai
export NEMOCLAW_MODEL="$model"
export NEMOCLAW_SANDBOX_NAME="$sandbox"
export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1

nemohermes onboard \
  --fresh \
  --non-interactive \
  --yes \
  --yes-i-accept-third-party-software \
  --agent hermes \
  --name "$sandbox"
