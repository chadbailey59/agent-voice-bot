# agent-voice-bot

This is the Python bot workspace inside the repository monorepo. Run all `uv`
and test commands in this directory.

A responsive voice loop in front of a slower agent loop, as two workers on a
shared Pipecat bus:

- `main`: a pipeline worker that is both the media path and the voice loop —
  transport, STT, an inline LLM, and TTS. The LLM answers simple turns directly,
  forwards agentic work with `send_to_agent_loop` (fire-and-forget over the bus),
  and can `stop_agent_loop` to cancel it. Agent results come back as bus job
  responses and are injected as developer messages.
- `agent-loop`: a stateful bus worker that owns agent-loop routing (new task vs.
  refinement of a running one) and cancellation, against an OpenClaw agent in a
  NemoClaw sandbox.

## Layout

- `core/` — framework-neutral runtime, event, and capability contracts.
- `runtimes/openclaw.py` — the OpenClaw Gateway websocket client.
- `services/profiles.py` — the `hosted` and `local` voice stacks.

## Run

```bash
uv sync --extra dev
export DEEPGRAM_API_KEY=... BASETEN_API_KEY=... GRADIUM_API_KEY=...
uv run agent-voice-bot -t webrtc --port 7860
```

The `webrtc` runner transport is Pipecat SmallWebRTC. Use `-t eval` for a
headless bot.

Example environment profiles live in `configs/`. Load one without overwriting
secrets already exported by the shell:

```bash
set -a
. configs/hosted.env
set +a
uv run agent-voice-bot -t webrtc --port 7860
```

The bot loads `.env` with `override=False`, so a loaded profile (or anything
already exported) takes precedence and `.env` only fills in unset variables. To
skip the `.env` load entirely, set `AGENT_VOICE_SKIP_DOTENV=1`.

## Voice profiles

`VOICE_PROFILE` selects STT, LLM, and TTS together. Mixing providers across
profiles is not supported.

### `hosted` (default)

```bash
VOICE_PROFILE=hosted
DEEPGRAM_API_KEY=...
BASETEN_API_KEY=...
GRADIUM_API_KEY=...
# Optional: a dedicated Baseten deployment instead of the shared Model APIs.
# Both values come from the Baseten dashboard and move together.
# BASETEN_BASE_URL=https://model-{model_id}.api.baseten.co/environments/production/sync/v1
# BASETEN_MODEL=nvidia/NVIDIA-Nemotron-3-Nano
# GRADIUM_VOICE_ID=
```

`BASETEN_MODEL` defaults to `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B`, the
Nemotron slug the shared Model APIs endpoint serves by name. Nano and Super are
faster and better suited to a voice loop, but are served from dedicated
deployments, so they need `BASETEN_BASE_URL` too.

### `local`

Needs `uv sync --extra nvidia`, which pulls in `riva-client`.

```bash
VOICE_PROFILE=local
NVIDIA_ASR_SERVER=localhost:50051
NVIDIA_TTS_SERVER=localhost:50052
NVIDIA_LLM_BASE_URL=http://localhost:8000/v1
NVIDIA_LLM_MODEL=nvidia/nvidia-nemotron-3-nano
```

Each NIM listens on gRPC 50051 in its own container, hence the remapped TTS port
above. Riva binds the acoustic model at container start, and the client sends an
empty model name, so `NVIDIA_ASR_MODEL` and `NVIDIA_TTS_MODEL` only label
metrics — redeploy the NIM to change models. `NVIDIA_TTS_VOICE` does apply per
request and defaults to `Magpie-Multilingual.EN-US.Aria`.

No API key is needed: a local NIM authenticates nothing. Set `NVIDIA_API_KEY`
with `NVIDIA_ASR_USE_SSL` and `NVIDIA_TTS_USE_SSL` to reach a remote endpoint
instead, plus `NVIDIA_TTS_FUNCTION_ID` for NVIDIA Cloud Functions. See
`.env.example` for the full list.

Deploying the speech NIMs — including picking a Parakeet build with a streaming
profile, which not all of them have — is covered by the
[`nvidia-riva-speech`](../skills/nvidia-riva-speech/SKILL.md) skill. Run
`npx skills add .` from the repository root to hand it to a coding agent.

## Agent loop

The agent loop always talks to an OpenClaw Gateway published by a NemoClaw
sandbox. The default port is the sandbox's 18790, not OpenClaw's own 18789.

```bash
OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18790
OPENCLAW_SESSION_KEY=agent:main:main
OPENCLAW_TIMEOUT_SECS=300
# OPENCLAW_TOKEN=$(nemoclaw nc gateway-token --quiet)
# OPENCLAW_PASSWORD=...
```

The runtime uses one lifecycle:

- `start` opens a Gateway connection and issues `chat.send`, returning a run
  handle.
- `events` streams that run's `chat` frames as normalized events; `collect_result`
  folds them into a terminal result.
- `send_followup` applies a refinement to the live run with `sessions.steer`.
- `stop` preempts the run with `chat.abort` when the voice loop calls
  `stop_agent_loop`.

Frames for other runs on the same socket are ignored, so a concurrent run cannot
terminate this one's stream or leak text into its result.

The voice loop exposes two tools: `send_to_agent_loop` (forward any input — new
work or a follow-up) and `stop_agent_loop` (preemptively cancel running work).
The voice loop only decides answer-vs-forward; the agent loop owns the
new-vs-steer routing.

## Tests

```bash
uv run pytest
uv run ruff check .
```

Deterministic and credential-free. The OpenClaw tests stand up a real websocket
server in-process rather than mocking the connection. The local-profile tests
skip unless the `nvidia` extra is installed.
