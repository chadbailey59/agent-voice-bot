#!/usr/bin/env bash
set -euo pipefail

sandbox="${NEMOCLAW_SANDBOX_NAME:-nh}"
nemohermes "$sandbox" recover
nemohermes "$sandbox" status
nemohermes "$sandbox" doctor
curl --fail --silent --show-error http://127.0.0.1:8642/health
printf '\n'
