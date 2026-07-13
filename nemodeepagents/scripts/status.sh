#!/usr/bin/env bash
set -euo pipefail

sandbox="${NEMOCLAW_SANDBOX_NAME:-nd}"
nemoclaw "$sandbox" recover
nemoclaw "$sandbox" status
nemoclaw "$sandbox" doctor
nemoclaw "$sandbox" exec --no-tty -- dcode status

