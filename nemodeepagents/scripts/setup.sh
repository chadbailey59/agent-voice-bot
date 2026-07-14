#!/usr/bin/env bash
set -euo pipefail

sandbox="${NEMOCLAW_SANDBOX_NAME:-nd}"
model="${NEMOCLAW_MODEL:-nemotron-3-nano:30b-partial20}"

export NEMOCLAW_AGENT=langchain-deepagents-code
export NEMOCLAW_PROVIDER=ollama
export NEMOCLAW_MODEL="$model"
export NEMOCLAW_SANDBOX_NAME="$sandbox"
export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1

nemoclaw onboard \
  --fresh \
  --non-interactive \
  --yes \
  --yes-i-accept-third-party-software \
  --agent langchain-deepagents-code \
  --name "$sandbox"

