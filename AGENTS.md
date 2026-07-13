# Agent Voice Bot contributor guide

## Repository layout

This is a monorepo. The Python package and all Python tooling live in `bot/`.

- `bot/src/agent_voice_bot/core/` contains framework-neutral runtime contracts.
- `bot/src/agent_voice_bot/runtimes/` contains backend construction and adapters.
- `bot/src/agent_voice_bot/services/` contains speech and voice-LLM providers.
- `bot/src/agent_voice_bot/features/` contains composable runtime decorators.
- `bot/src/agent_voice_bot/nemo/` contains the optional Nemo/OpenShell bridge.
- `bot/tests/` and `bot/evals/` contain tests and Pipecat eval scenarios.
- `nemoclaw/` and `nemohermes/` contain local sandbox profiles and scripts.
- `docs/agent-runtime-interface.md` documents the backend lifecycle contract.

Read the root `README.md` for architecture and model-provider configuration,
then `bot/README.md` for detailed runtime settings.

## Development commands

Run Python commands from `bot/`:

```bash
cd bot
uv sync --extra dev
uv run pytest
uv run agent-voice-bot -t webrtc --port 7860
```

Use `-t eval` for a headless bot. Do not assume commands run from the repository
root, because `pyproject.toml` and `uv.lock` intentionally live in `bot/`.

## Architecture constraints

- Keep the latency-sensitive voice loop separate from the slower agent loop.
- Keep `core/` free of Pipecat, Nemo, and backend-specific dependencies.
- Implement backend variance behind the `start`, `wait`, `send_followup`, and
  `stop` runtime lifecycle instead of branching the voice worker.
- Add cross-cutting behavior as ordered decorators in `features/` when possible.
- Keep OpenShell collection outside the real-time media process and communicate
  through the normalized JSONL event boundary.
- Preserve each backend's real capabilities. Do not report that a follow-up was
  steered or a run was cancelled unless the backend confirms it.

## Configuration and secrets

Copy `bot/.env.example` to `bot/.env` for local work. Never commit `.env`, API
keys, tokens, credentials, or private endpoint details. Environment variables
already exported by the shell take precedence over `.env`; profiles in
`bot/configs/` are loaded explicitly.

The voice-loop model and agent-loop model are independent. The voice loop is
currently an OpenAI Responses provider. Agent backends may use local or hosted
inference through an OpenAI-compatible endpoint, Hermes, OpenClaw, or
NemoHermes. Keep documentation and `.env.example` synchronized when adding or
renaming configuration variables.

## Testing expectations

- Run `cd bot && uv run pytest` after Python or configuration changes.
- Add unit tests for new runtime capabilities and configuration paths.
- Keep eval scenarios deterministic unless they are explicitly live-backend
  smoke tests.
- Treat files under `bot/evals/test-runs/` as captured artifacts, not source to
  hand-edit.
- Run `git diff --check` before committing, excluding known captured log
  whitespace only when those artifacts are intentionally included.

## Scope and upstreaming

This repository is a staging area for work that may later be proposed to
`NVIDIA/NemoClaw`. Keep changes reviewable, avoid machine-specific assumptions,
and document any required host, Docker, Ollama, or OpenShell state before an
upstream PR.
