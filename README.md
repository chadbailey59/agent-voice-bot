# Nemo agent voice frontend

This monorepo explores a responsive Pipecat voice frontend for agents managed by
[NemoClaw](https://github.com/NVIDIA/NemoClaw) and examples intended for
[`nemoclaw-community`](https://github.com/NVIDIA/nemoclaw-community).

This is an independently maintained community project. It is not an NVIDIA
product and is not supported by NVIDIA.

## Example

[Watch a three-minute example of the voice frontend delegating work to an agent](docs/media/agent-voice-bot-demo.mp4).

## Layout

- [`bot/`](bot/) — the Pipecat voice application, adapters, tests, and evals.
- [`nemoclaw/`](nemoclaw/) — local OpenClaw-in-NemoClaw profile and smoke checks.
- [`nemohermes/`](nemohermes/) — local Hermes-in-NemoClaw profile and smoke checks.
- [`nemodeepagents/`](nemodeepagents/) — local LangChain Deep Agents Code profile and smoke checks.
- [`docs/agent-runtime-interface.md`](docs/agent-runtime-interface.md) — proposed
  framework-neutral interface and execution pattern.

NemoHermes is a Hermes-selected alias of the NemoClaw CLI, not an independent
sandbox manager. The two support folders intentionally create different named
sandboxes so both harnesses can be exercised from the same checkout.

## How the bot works

The bot separates real-time conversation from slower agent work. This is the
main reason it can keep listening and answering quick questions while an agent
is researching, using tools, or changing files in the background.

```text
microphone -> speech-to-text -> voice loop -> text-to-speech -> speaker
                                  |
                                  +-> agent loop -> OpenClaw, Hermes, or Deep Agents Code
                                                        |
                                  voice loop <- result --+
```

There are two cooperating Pipecat workers, each with a distinct loop:

- **Voice loop.** The `main` worker moves audio through the transport, Deepgram
  speech-to-text, a fast conversational LLM, Cartesia text-to-speech, and back
  to the user, maintaining the conversation context. For each turn the LLM
  decides whether to answer immediately or call `send_to_agent_loop`.
  Forwarded work receives a very short spoken acknowledgement, leaving the
  voice loop free to handle another turn. It can also call `stop_agent_loop`
  when the user asks to cancel and `end_conversation` when the user says
  goodbye. Forwarding is fire-and-forget over the bus, so the media path never
  blocks on agent work.
- **Agent loop.** The `agent-loop` worker owns the one active background task,
  its backend run handle, and all backend-specific behavior. When idle, a
  forwarded message starts a run. When busy, another forwarded message is
  treated as a refinement of that run. A completed result is sent urgently
  over the bus, and the voice loop converts it into a concise spoken answer.

This split creates two useful concurrent paths: the short, latency-sensitive
voice path and the potentially long-running agent path. A quick question can
therefore stay in the voice path even while agent work is in progress. A
correction intended for that work is forwarded to the agent path instead.

### Follow-ups and cancellation

The voice loop always uses the same two controls; the selected agent adapter
determines what they can actually do:

- OpenClaw supports live refinements with `sessions.steer` and confirmed
  cancellation with `chat.abort`.
- Direct Hermes `/v1/runs` streams progress and supports stopping a run, but it
  does not expose live steering. The bot tells the user when a refinement could
  not be applied instead of pretending it was accepted.
- NemoHermes uses the sandbox's OpenAI-compatible chat-completions endpoint. It
  logs a Hermes session ID when the endpoint supplies one, but the current
  adapter does not reuse that ID on later requests. This request/response
  surface also does not provide streaming, live steering, or guaranteed
  server-side cancellation.
- NemoClaw + Deep Agents Code runs headless `dcode -n` tasks through the
  sandbox CLI. The bot can cancel its local process, but the terminal harness
  exposes neither live steering nor headless session continuation.

ACP support is coming soon. A future direct ACP adapter will add persistent
agent sessions and continuous conversation support beyond the current headless
Deep Agents Code task integration.

## Direct runtimes versus NemoClaw

The bot's voice and agent loops are the same in every configuration. NemoClaw
is an optional execution and observability layer around an OpenClaw, Hermes, or
Deep Agents Code runtime; it is not a second agent loop.

Running **directly with OpenClaw or Hermes** gives the bot the native runtime
features exposed by that backend: session continuity, results and progress,
plus steering and cancellation where supported. This is the simplest setup and
is useful when the agent already runs in an environment you trust.

Running **through NemoClaw** adds:

- an OpenShell sandbox boundary around the agent process;
- policy and approval signals from that sandbox;
- sandbox-health and tool-start/tool-finish events, even when those events are
  not part of the underlying agent protocol; and
- a normalized JSONL telemetry stream combining agent and OpenShell events for
  debugging, auditing, and later UI integration.

The OpenShell collector remains outside the real-time media process. It writes
normalized events such as `policy.denied`, `approval.required`,
`sandbox.unhealthy`, `tool.started`, and `tool.finished` to a JSONL boundary.
The bot merges matching events into the active run and can record the complete
normalized stream to a second JSONL file. This keeps Nemo-specific dependencies
out of the core runtime and means the same observation and telemetry decorators
can be added to OpenClaw, Hermes, or Deep Agents Code.

The practical feature matrix is:

| Configuration | Agent API | Live refinement | Cancellation | Extra sandbox events | Normalized telemetry |
| --- | --- | --- | --- | --- | --- |
| Direct OpenClaw | Gateway WebSocket | Yes | Yes | No | No |
| Direct Hermes | `/v1/runs` + SSE | No | Yes | No | No |
| NemoClaw + OpenClaw | Gateway WebSocket | Yes | Yes | Yes | Yes |
| NemoHermes | OpenAI-compatible HTTP | No | Local request cancellation only | Yes | Yes |
| NemoClaw + Deep Agents Code | `nemoclaw exec` + `dcode -n` | No | Local process cancellation | Yes | Yes |

The Nemo features are enabled by configuration, not by branching the bot:

```bash
AGENT_VOICE_FEATURES=openshell-events,nemo-telemetry
OPENSHELL_EVENTS_FILE=/tmp/agent-voice-openshell-events.jsonl
AGENT_VOICE_TELEMETRY_FILE=/tmp/agent-voice-telemetry.jsonl
```

See [`bot/README.md`](bot/README.md) for backend endpoints, environment profiles,
and the exact lifecycle contract used by every adapter.

## Quick start

If you don't already have Hermes, OpenClaw, or NemoClaw installed, the quickest way to get an agent to try is to use NemoClaw's setup. [They walk you through the process here](https://github.com/NVIDIA/NemoClaw), but they also link directly to [a starter prompt to give to Claude Code or Codex](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/home#from-your-coding-agent) to set up an agent that way.

If you have NemoClaw already set up, the existing local Hermes sandbox can be checked with:

```bash
./nemohermes/scripts/status.sh
./nemohermes/scripts/smoke.sh
```

Optionally, create and check a separate OpenClaw sandbox after the Hermes profile is ready:

```bash
./nemoclaw/scripts/setup.sh
./nemoclaw/scripts/status.sh
```

Create and check a separate LangChain Deep Agents Code sandbox with a current
NemoClaw release:

```bash
./nemodeepagents/scripts/setup.sh
./nemodeepagents/scripts/status.sh
./nemodeepagents/scripts/smoke.sh
```

Run the bot from its workspace:

```bash
cd bot
uv sync --extra dev
uv run agent-voice-bot -t webrtc --port 7860
```

See the profile READMEs in `nemoclaw`, `nemohermes`, and `nemodeepagents` for
backend-specific environment variables and setup details.

## Verification

The default test suite is deterministic and does not require live speech,
model, or agent credentials:

```bash
cd bot
uv sync --extra dev
uv run pytest
```

Live-backend smoke checks are documented in each profile README. They require
the corresponding local sandbox or agent service and are intentionally kept
separate from the default test suite.

## Support and compatibility

NemoClaw is evolving quickly. The checked-in profiles document the commands and
runtime boundaries they exercise, but they are not a compatibility guarantee
for every NemoClaw, OpenShell, Pipecat, or agent-framework release. Please open
an issue in this repository with the host platform, component versions, selected
profile, and failing command when reporting a reproducible problem.

## License

Licensed under the [Apache License 2.0](LICENSE).

## Choosing local or hosted LLMs

The bot uses LLMs in two different places, and they are configured separately:

- The **voice loop** is the fast coordinator that decides whether to answer or
  delegate. It currently uses OpenAI's Responses API. Set `OPENAI_API_KEY` and,
  optionally, `VOICE_LOOP_MODEL` (the default is `gpt-5.4-mini`).
- The **agent loop** does delegated work. It can call an OpenAI-compatible model
  directly, or hand work to an agent framework such as Hermes, OpenClaw, or
  Deep Agents Code. Its
  model and credentials do not have to match the voice loop.

Start by copying the environment template:

```bash
cd bot
cp .env.example .env
```

The `.env` file is ignored by Git. It still needs `OPENAI_API_KEY`,
`DEEPGRAM_API_KEY`, and `CARTESIA_API_KEY` for the current voice and speech
services.

### Direct local model

To send delegated work straight to a local server that implements
`POST /v1/chat/completions` (for example, Ollama's OpenAI-compatible API), add
this to `bot/.env`:

```dotenv
AGENT_LOOP_MODE=openai
AGENT_LOOP_OPENAI_BASE_URL=http://127.0.0.1:11434/v1
AGENT_LOOP_OPENAI_MODEL=your-local-model
AGENT_LOOP_OPENAI_API_KEY=local-placeholder
AGENT_LOOP_REASONING_EFFORT=high
```

The API key may be omitted when the local endpoint does not require one. The
model name must match a model exposed by that server. This direct mode provides
chat-completion inference, not the tools or session controls of a full agent
framework.

### Direct hosted model

The same adapter can call an external hosted OpenAI-compatible endpoint:

```dotenv
AGENT_LOOP_MODE=openai
AGENT_LOOP_OPENAI_BASE_URL=https://provider.example/v1
AGENT_LOOP_OPENAI_MODEL=provider-model-id
AGENT_LOOP_OPENAI_API_KEY=your-provider-key
AGENT_LOOP_REASONING_EFFORT=high
```

Use the provider's exact base URL and model ID. `AGENT_LOOP_OPENAI_API_KEY`
falls back to `OPENAI_API_KEY` when it is unset, so set it explicitly when the
agent model is hosted by a different provider.

### Models behind Hermes, OpenClaw, or NemoClaw

When `AGENT_LOOP_MODE=hermes`, `openclaw`, `nemohermes`, or `deepagents`, the
bot connects to the framework's execution surface; the framework itself chooses
the local or hosted model.
Configure the inference provider in that framework first, then point the bot at
the resulting endpoint:

| Agent mode | Bot connection | Where the LLM is selected |
| --- | --- | --- |
| `hermes` | `AGENT_LOOP_HERMES_BASE_URL` | Hermes server configuration |
| `openclaw` | `AGENT_LOOP_OPENCLAW_GATEWAY_URL` | OpenClaw provider/model configuration |
| `nemohermes` | `AGENT_LOOP_NEMOHERMES_BASE_URL` | NemoClaw sandbox/Hermes configuration |
| `deepagents` | `AGENT_LOOP_DEEPAGENTS_SANDBOX` | NemoClaw LangChain Deep Agents Code sandbox |

The checked-in Nemo profiles default to local Ollama. Override
`NEMOCLAW_MODEL` when creating either sandbox; the OpenClaw profile also accepts
`NEMOCLAW_ENDPOINT_URL` for a different OpenAI-compatible endpoint. See
[`nemoclaw/README.md`](nemoclaw/README.md),
[`nemohermes/README.md`](nemohermes/README.md),
[`nemodeepagents/README.md`](nemodeepagents/README.md), and
[`bot/README.md`](bot/README.md) for setup commands and all backend-specific
variables.

## Choosing local or hosted speech

Speech is selected separately from either LLM, through `SPEECH_PROVIDER`:

| Provider | STT | TTS | Runs |
| --- | --- | --- | --- |
| `deepgram-cartesia` (default) | Deepgram | Cartesia | Hosted, needs API keys |
| `nvidia-riva` | Parakeet | Magpie | Local, on your own GPU |

`nvidia-riva` keeps audio on the machine by talking gRPC to two self-hosted
[NVIDIA Riva NIM](https://docs.nvidia.com/nim/riva/asr/latest/getting-started.html)
containers. Parakeet is the streaming member of NVIDIA's ASR family and is
built for latency, which is what the voice loop needs; its sibling Canary is
more accurate but segmented, so it does not stream. No API key is involved,
because a local NIM authenticates nothing.

Install the extra and select the provider:

```bash
cd bot
uv sync --extra nvidia
echo "SPEECH_PROVIDER=nvidia-riva" >> .env
```

### Deploying the NIMs

Pick a Parakeet NIM that has a streaming profile. **Not all of them do** —
`parakeet-0.6b-tdt` ships only `mode=ofl` (offline) profiles and cannot serve
this pipeline, which fails at runtime rather than at deploy time.
`parakeet-1-1b-ctc-en-us` offers `mode=str`, and that is what the bot expects:

```bash
export NGC_API_KEY=nvapi-...   # from ngc.nvidia.com

docker run -d --name parakeet-asr --gpus all --shm-size=8GB \
  -e NGC_API_KEY -e NIM_TAGS_SELECTOR="mode=str,diarizer=disabled,vad=default" \
  -p 50051:50051 -p 9000:9000 -v ~/.cache/nim:/opt/nim/.cache \
  nvcr.io/nim/nvidia/parakeet-1-1b-ctc-en-us:latest

docker run -d --name magpie-tts --gpus all --shm-size=8GB \
  -e NGC_API_KEY \
  -p 50052:50051 -p 9001:9000 -v ~/.cache/nim:/opt/nim/.cache \
  nvcr.io/nim/nvidia/magpie-tts-multilingual:latest
```

Each NIM serves gRPC on 50051 inside its own container, hence the remapped TTS
port. Both images are roughly 25 GB, and the first start downloads a model
profile and builds TensorRT engines, so allow 15-25 minutes before
`curl localhost:9000/v1/health/ready` reports ready. Point the bot at both:

```dotenv
NVIDIA_ASR_SERVER=localhost:50051
NVIDIA_TTS_SERVER=localhost:50052
```

### Models and voices

Riva binds the acoustic model when the container starts, through `CONTAINER_ID`
and `NIM_TAGS_SELECTOR`. To swap Parakeet for another ASR model, or Magpie for
`fastpitch-hifigan-en-us`, redeploy the NIM; `NVIDIA_ASR_MODEL` and
`NVIDIA_TTS_MODEL` only label metrics. `NVIDIA_TTS_VOICE` does take effect at
runtime and must name a voice the deployed TTS model actually serves; list them
with `curl localhost:9001/v1/audio/list_voices`. The remaining variables are in
[`bot/.env.example`](bot/.env.example).

Self-hosting a NIM is covered by the NVIDIA AI Enterprise License, which is free
for development through the NVIDIA Developer Program. It needs an NVIDIA GPU of
compute capability 8.0 or higher; GeForce RTX 40xx and 50xx qualify alongside
the datacenter cards. On an RTX 5090 the pair resides in about 17 GB of VRAM,
measured at 4 GB for Parakeet and 13 GB for Magpie. Both load their models at
startup and hold that memory, so a card already hosting a local LLM may not fit
all three.

Give the ASR NIM room before it starts. When too little VRAM is free, it builds
its TensorRT engines successfully and only then fails to create the execution
context, reporting `CUDA error 2 creating stream for constant data`. Triton
exits, the container follows with status 0, and the log fills with
`illegal memory access` noise from the teardown rather than the allocation
failure itself.
