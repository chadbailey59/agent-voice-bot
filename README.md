# agent-voice-bot

Reference Pipecat voice bot: a responsive voice loop in front of a slower agent loop.

The runtime has three workers on a shared Pipecat bus:

- `main`: transport, Deepgram STT, Cartesia TTS, and the bus bridge.
- `voice-loop`: an `LLMWorker` using `gpt-5.4-mini`. It answers simple turns directly, forwards agentic work with `send_to_agent_loop`, and can `stop_agent_loop` to cancel it.
- `agent-loop`: a stateful bus worker that owns agent-loop routing (new task vs. refinement of a running one) and cancellation, and adapts the work to mock, REST HTTP, OpenAI-compatible chat completions, MCP, Hermes, NemoHermes, or OpenClaw.

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
