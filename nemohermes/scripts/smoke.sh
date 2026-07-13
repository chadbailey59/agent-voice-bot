#!/usr/bin/env bash
set -euo pipefail

sandbox="${NEMOCLAW_SANDBOX_NAME:-nh}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root/bot"
uv run agent-voice-bot-nemohermes-check --sandbox "$sandbox" --completion
