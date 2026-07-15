# agent-voice-bot

This is the Python bot workspace inside the repository monorepo. Run all `uv`
and test commands in this directory.

## Architecture

The bot is assembled from independent providers and decorators:

- `core/` defines framework-neutral runtime, event, capability, approval, and
  presentation contracts.
- `runtimes/` builds direct Hermes, OpenClaw, Deep Agents Code, MCP, REST,
  OpenAI-compatible, and mock runtimes without in-process Nemo dependencies.
- `services/` injects speech and voice-coordinator providers.
- `features/` supplies ordered runtime decorators for observation, guardrails,
  and telemetry.
- `nemo/` bolts OpenShell events and Nemo telemetry onto any direct runtime.

Example environment profiles live in `configs/`. Load one without overwriting
secret values already exported by the shell:

```bash
set -a
. configs/direct-openclaw.env
set +a
uv run agent-voice-bot -t webrtc --port 7860
```

The bot loads `.env` with `override=False`, so a loaded profile (or anything
already exported) takes precedence and `.env` only fills in unset variables. To
skip the `.env` load entirely, set `AGENT_VOICE_SKIP_DOTENV=1`.

Nemo profiles use a JSONL boundary so an OpenShell audit collector can remain a
separate process. Each input record uses a normalized `kind` such as
`policy.denied`, `approval.required`, `sandbox.unhealthy`, `tool.started`, or
`tool.finished`, plus optional `run_id`, `message`, and metadata fields.

Reference Pipecat voice bot: a responsive voice loop in front of a slower agent loop.

The runtime has two workers on a shared Pipecat bus:

- `main`: a pipeline worker that is both the media path and the voice loop — transport, Deepgram STT, an inline `gpt-5.4-mini` LLM, and Cartesia TTS. The LLM answers simple turns directly, forwards agentic work with `send_to_agent_loop` (fire-and-forget over the bus), and can `stop_agent_loop` to cancel it. Agent results come back as bus job responses and are injected as developer messages.
- `agent-loop`: a stateful bus worker that owns agent-loop routing (new task vs. refinement of a running one) and cancellation, and adapts the work to mock, REST HTTP, OpenAI-compatible chat completions, MCP, Hermes, NemoHermes, LangChain Deep Agents Code, or OpenClaw.

## Run

```bash
export OPENAI_API_KEY=...
export DEEPGRAM_API_KEY=...
export CARTESIA_API_KEY=...

uv run agent-voice-bot -t webrtc --port 7860
```

The `webrtc` runner transport is Pipecat SmallWebRTC. Use `-t eval` for
headless eval scenarios.

For local development against the Pipecat checkout in `/home/chad/Code/pipecat`:

```bash
PYTHONPATH=/home/chad/Code/pipecat/src:src python -m agent_voice_bot.bot -t eval --port 7860
```

## Speech Providers

`SPEECH_PROVIDER` selects the STT/TTS pair. It is independent of both the voice-loop
and agent-loop models.

```bash
# hosted default: Deepgram STT + Cartesia TTS
SPEECH_PROVIDER=deepgram-cartesia

# fully local: Parakeet ASR + Magpie TTS on self-hosted Riva NIMs
# requires `uv sync --extra nvidia`; no API key, a local NIM authenticates nothing
SPEECH_PROVIDER=nvidia-riva
NVIDIA_ASR_SERVER=localhost:50051
NVIDIA_TTS_SERVER=localhost:50052
```

Each NIM listens on gRPC 50051 in its own container, hence the remapped TTS port
above. Deploy the ASR NIM with a streaming profile — `parakeet-1-1b-ctc-en-us` with
`NIM_TAGS_SELECTOR=mode=str`. Not every Parakeet NIM can stream: `parakeet-0.6b-tdt`
ships offline-only (`mode=ofl`) profiles and cannot serve this pipeline. The root
`README.md` has the full `docker run` commands.

Riva binds the acoustic model at container start (`CONTAINER_ID`,
`NIM_TAGS_SELECTOR`), and the client sends an empty model name, so `NVIDIA_ASR_MODEL`
and `NVIDIA_TTS_MODEL` only label metrics — redeploy the NIM to change models.
`NVIDIA_TTS_VOICE` does apply per request and defaults to
`Magpie-Multilingual.EN-US.Aria`; a `fastpitch-hifigan-en-us` NIM serves other
voices and needs an explicit name. Set `NVIDIA_API_KEY` with `NVIDIA_ASR_USE_SSL`
and `NVIDIA_TTS_USE_SSL` to reach a remote endpoint instead, plus
`NVIDIA_TTS_FUNCTION_ID` for NVIDIA Cloud Functions. See `.env.example` for the
full list.

## Agent Loop Modes

```bash
# default deterministic stub for evals/tests
AGENT_LOOP_MODE=mock
AGENT_LOOP_MOCK_DELAY_SECS=1.0

# REST server
AGENT_LOOP_MODE=rest
AGENT_LOOP_REST_URL=http://localhost:8080/run

# OpenAI-compatible endpoint
AGENT_LOOP_MODE=openai
AGENT_LOOP_OPENAI_BASE_URL=http://localhost:11434/v1
AGENT_LOOP_OPENAI_MODEL=hermes-agent
AGENT_LOOP_REASONING_EFFORT=high
AGENT_LOOP_OPENAI_API_KEY=dummy

# MCP server
AGENT_LOOP_MODE=mcp
AGENT_LOOP_MCP_TRANSPORT=stdio
AGENT_LOOP_MCP_COMMAND=python
AGENT_LOOP_MCP_ARGS='["server.py"]'
AGENT_LOOP_MCP_TOOL=run_agent

# Hermes API server (/v1/runs + SSE events)
AGENT_LOOP_MODE=hermes
AGENT_LOOP_HERMES_BASE_URL=http://127.0.0.1:8765
AGENT_LOOP_HERMES_API_KEY=$API_SERVER_KEY
AGENT_LOOP_HERMES_SESSION_KEY=agent-voice-bot

# NemoHermes sandbox OpenAI-compatible API (default sandbox: nh)
AGENT_LOOP_MODE=nemohermes
AGENT_LOOP_NEMOHERMES_BASE_URL=http://127.0.0.1:8642/v1
AGENT_LOOP_NEMOHERMES_MODEL=hermes-agent

# NemoClaw LangChain Deep Agents Code sandbox (default sandbox: nd)
AGENT_LOOP_MODE=deepagents
AGENT_LOOP_DEEPAGENTS_SANDBOX=nd

# OpenClaw Gateway WebSocket
AGENT_LOOP_MODE=openclaw
AGENT_LOOP_OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18789
AGENT_LOOP_OPENCLAW_SESSION_KEY=agent:main:main
# AGENT_LOOP_OPENCLAW_TOKEN=...
# AGENT_LOOP_OPENCLAW_PASSWORD=...
```

The agent-loop adapter uses the same lifecycle for every backend:

- `start` returns a backend run handle.
- `wait` streams or waits for the terminal result.
- `send_followup` tries to apply a refinement to the active handle.
- `stop` cancels the active handle when the voice loop calls `stop_agent_loop`.

Hermes mode uses `POST /v1/runs`, `GET /v1/runs/{run_id}/events`, and
`POST /v1/runs/{run_id}/stop`. The Hermes HTTP runs surface does not expose live
steering, so follow-ups are acknowledged as not applied unless you stop and
resend. OpenClaw mode uses Gateway WS `chat.send`, `chat` events, `sessions.steer`
for active follow-ups, and `chat.abort` for cancellation.

Deep Agents Code mode invokes the terminal-oriented NemoClaw harness as
`nemoclaw <sandbox> exec -- dcode -n <task>`. It supports cancelling that local
process, but does not claim live steering or session continuation because the
harness has no agent gateway.

## NemoHermes

NemoHermes exposes a Hermes sandbox through an OpenAI-compatible API, normally
`http://127.0.0.1:8642/v1`. The `nemohermes` mode is separate from `hermes`
because the latter is for a `/v1/runs` + SSE API server.

Check the local `nh` sandbox and API:

```bash
uv run agent-voice-bot-nemohermes-check --sandbox nh
```

Run the bot against NemoHermes:

```bash
AGENT_LOOP_MODE=nemohermes \
AGENT_LOOP_NEMOHERMES_BASE_URL=http://127.0.0.1:8642/v1 \
AGENT_LOOP_NEMOHERMES_MODEL=hermes-agent \
uv run agent-voice-bot -t webrtc --port 7860
```

Add `--completion` to the check command when you want it to issue a real
`/v1/chat/completions` request. Keep `AGENT_LOOP_TIMEOUT_SECS` high enough for
the model running in the sandbox.

## LangChain Deep Agents Code

Create the dedicated `nd` profile by following
[`../nemodeepagents/README.md`](../nemodeepagents/README.md), then load its bot
configuration from this directory:

```bash
set -a
source configs/nemoclaw-deepagents.env
set +a
uv run agent-voice-bot -t webrtc --port 7860
```

Use `AGENT_LOOP_DEEPAGENTS_COMMAND` if the NemoClaw executable has a nonstandard
name or path, and `AGENT_LOOP_DEEPAGENTS_SANDBOX` to select another registered
Deep Agents Code sandbox.

## Evals

Start the bot with the eval transport, then run:

```bash
PYTHONPATH=/home/chad/Code/pipecat/src:src pipecat eval run evals/scenarios/*.yaml --bot-url ws://localhost:7860
```

For a real NemoHermes agent-loop smoke eval, start the bot with eval transport
and `AGENT_LOOP_MODE=nemohermes`, then run:

```bash
uv run pipecat eval run evals/scenarios/voice_then_agent_world_cup.yaml --bot-url ws://localhost:7860
```

Or let the eval suite spawn that live-backend bot for you:

```bash
uv run pipecat eval suite evals/nemohermes_manifest.yaml
```

The voice loop exposes two tools to the agent loop: `send_to_agent_loop` (forward
any input — new work or a follow-up) and `stop_agent_loop` (preemptively cancel
running work). The voice loop only decides answer-vs-forward; the agent loop owns
all backend-specific variance (new-vs-steer routing, how/whether a refinement is
applied, whether a backend can truly preempt).

The scenarios cover:

- `voice_loop_basic` — the voice loop answers simple questions directly.
- `delegates_agent_work` — complex work is forwarded via `send_to_agent_loop`.
- `voice_loop_stays_responsive` — a quick question is answered while a agent task runs.
- `return_path` — a forwarded result comes back and is spoken to the user (the
  mock backend returns confirmation code `ZEBRA-4417`, which the relay must preserve).
- `quick_question_while_working` — a simple question is answered directly,
  not forwarded, while the agent loop is busy.
- `forwards_followup` — a follow-up that refines an in-flight task is *forwarded*
  with the same `send_to_agent_loop` tool rather than answered locally. This only
  checks voice-loop routing. Whether a backend can actually apply a refinement to
  running work (live injection, cancel-and-restart, queueing, or not at all) is
  framework-specific and validated per-framework, not by this generic suite.
- `stop_agent_loop` — a request to cancel running work calls `stop_agent_loop`,
  which preemptively cancels the in-flight job over the bus.

Or run them as a suite:

```bash
uv run pipecat eval suite evals/manifest.yaml
```

The suite spawns the bot with `AGENT_LOOP_MOCK_DELAY_SECS=6` (see `manifest.yaml`)
so the mock agent loop is genuinely still running while the responsiveness,
steering, and return-path scenarios drive their follow-up turns. When running a
single scenario with `pipecat eval run --bot-url`, start the bot with a
multi-second `AGENT_LOOP_MOCK_DELAY_SECS` yourself for the same reason.
