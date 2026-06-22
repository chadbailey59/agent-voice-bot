# agent-voice-bot

Reference Pipecat voice bot: a responsive voice loop in front of a slower agent loop.

The runtime has three workers on a shared Pipecat bus:

- `main`: transport, Deepgram STT, Cartesia TTS, and the bus bridge.
- `voice-loop`: an `LLMWorker` using `gpt-5.4-mini`. It answers simple turns directly, forwards agentic work with `send_to_agent_loop`, and can `stop_agent_loop` to cancel it.
- `agent-loop`: a stateful bus worker that owns agent-loop routing (new task vs. refinement of a running one) and cancellation, and adapts the work to one of four backends: mock, REST HTTP, OpenAI-compatible chat completions, or MCP.

## Run

```bash
export OPENAI_API_KEY=...
export DEEPGRAM_API_KEY=...
export CARTESIA_API_KEY=...

uv run agent-voice-bot -t eval --port 7860
```

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
```

## Evals

Start the bot with the eval transport, then run:

```bash
PYTHONPATH=/home/chad/Code/pipecat/src:src pipecat eval run evals/scenarios/*.yaml --bot-url ws://localhost:7860
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
