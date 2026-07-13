#!/usr/bin/env bash
set -euo pipefail

sandbox="${NEMOCLAW_SANDBOX_NAME:-nc}"
nemoclaw "$sandbox" status
nemoclaw "$sandbox" doctor
