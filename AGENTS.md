# Agent Voice Bot contributor guide

## Scope

This branch supports exactly one agent backend — OpenClaw reached through a
NemoClaw sandbox's Gateway websocket — and two voice profiles, `hosted` and
`local`. Direct OpenClaw, Hermes, NemoHermes, Deep Agents, MCP, REST, plain
chat-completions, and the mock backend were all deliberately removed, along with
the runtime/speech/voice factory registries, the feature-decorator layer, the
OpenShell JSONL bridge, and the Pipecat eval suite. Do not reintroduce a
provider-registry abstraction for a single implementation; if a second backend
ever returns, restore the registry from git history at that point.

## Repository layout

This is a monorepo. The Python package and all Python tooling live in `bot/`.

- `bot/src/agent_voice_bot/` is six flat modules: `core.py` (runtime protocol and
  event types), `openclaw.py` (Gateway client), `voice.py` (the two voice stacks),
  `bot.py` and `agent_worker.py` (the Pipecat workers), and `config.py`. Do not
  reintroduce single-module packages.
- `bot/tests/` contains the tests.
- `nemoclaw/` contains the sandbox profile and scripts.
- `skills/` contains agent skills in the `vercel-labs/skills` format
  (`skills/<name>/SKILL.md`): a guided `agent-voice-bot-setup` front door, plus
  the optional local NVIDIA model setups. Keep host setup procedures for the
  Riva NIMs and local Nemotron there rather than expanding them back into the
  READMEs, which link to the skills instead. `.agents/skills/` is the installed
  mirror — update both.
- `docs/agent-runtime-interface.md` documents the backend lifecycle contract.

Read the root `README.md` for architecture and provider configuration, then
`bot/README.md` for detailed runtime settings.

## Development commands

Run Python commands from `bot/`:

```bash
cd bot
uv sync --extra dev
uv run pytest
uv run agent-voice-bot -t webrtc --port 7860
```

Add `--extra nvidia` to exercise the local profile; without it its tests skip.
Use `-t eval` for a headless bot. Do not assume commands run from the repository
root, because `pyproject.toml` and `uv.lock` intentionally live in `bot/`.

## Architecture constraints

- Keep the latency-sensitive voice loop separate from the slower agent loop.
- Keep `core.py` free of Pipecat and backend-specific dependencies.
- Implement backend behavior behind the `start`, `events`, `send_followup`, and
  `stop` runtime lifecycle instead of branching the voice worker.
- Keep the two voice profiles all-or-nothing. `VOICE_PROFILE` picks STT, LLM,
  and TTS together; do not add per-service override variables.
- Preserve the backend's real capabilities. Do not report that a follow-up was
  steered or a run was cancelled unless the Gateway confirms it.

## Configuration and secrets

Copy `bot/.env.example` to `bot/.env` for local work. Never commit `.env`, API
keys, tokens, credentials, or private endpoint details. Environment variables
already exported by the shell take precedence over `.env`; profiles in
`bot/configs/` are loaded explicitly.

The voice-loop model and the agent's model are independent and configured in
different places: `VOICE_PROFILE` (plus `BASETEN_MODEL` or `NVIDIA_LLM_MODEL`)
selects the voice loop's, while NemoClaw selects OpenClaw's and the bot never
sees it. Keep documentation and `.env.example` synchronized when adding or
renaming configuration variables.

## Testing expectations

- Run `cd bot && uv run pytest` after Python or configuration changes.
- Run `cd bot && uv run ruff check .` and fix or justify any findings. Docstring
  formatting rules follow the Google convention, as in Pipecat; missing-docstring
  rules (`D1`) are intentionally not enforced.
- Add unit tests for new runtime capabilities and configuration paths.
- Prefer the in-process websocket server in `tests/test_openclaw_runtime.py` over
  mocking the Gateway connection: the handshake and request/response correlation
  are the parts most likely to break, and a mock asserts nothing about either.
- Run `git diff --check` before committing.

## Scope and upstreaming

This repository is a staging area for work that may later be proposed to
`NVIDIA/NemoClaw`. Keep changes reviewable, avoid machine-specific assumptions,
and document any required host, Docker, Ollama, or OpenShell state before an
upstream PR.
