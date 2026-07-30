---
name: agent-voice-bot-setup
description: Guided end-to-end setup for the agent-voice-bot — point it at an OpenClaw agent in a NemoClaw sandbox, choose the hosted or local voice profile, and write bot/.env. Use when someone wants to set up, configure, install, or get started running this bot from scratch.
---

# Setting up the agent voice bot

This bot has exactly two things to settle. Do not guess the user's environment —
**ask the questions below and wire only what they choose.** Confirm each choice
before writing it, and edit `bot/.env` (copied from `bot/.env.example`) as you go.

1. **Agent loop** — always an OpenClaw agent in a NemoClaw sandbox. The only
   question is whether they have one already.
2. **Voice profile** — `hosted` or `local`. This one switch picks STT, LLM, and
   TTS together.

There is no other backend. If the user asks for Hermes, Deep Agents, a direct
OpenClaw Gateway outside a sandbox, an MCP server, or a plain chat-completions
agent loop, tell them this build does not support it rather than improvising a
mode — earlier versions had those and they were removed.

Read the root [`README.md`](../../README.md) for the architecture and
[`bot/.env.example`](../../bot/.env.example) for the full variable list.

## Step 0: prerequisites

```bash
cd bot
uv sync --extra dev
cp .env.example .env        # skip if .env already exists — don't clobber it
```

`bot/.env` is gitignored. Never write a key into any file other than `bot/.env`,
and never commit it.

## Step 1: the agent loop

**Ask: "Do you already have a NemoClaw sandbox running OpenClaw, or should we
create one?"**

### 1a. They already have one

Confirm it is up, then wire the bot to its forwarded Gateway:

```bash
./nemoclaw/scripts/status.sh
```

```dotenv
OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18790
OPENCLAW_SESSION_KEY=agent:main:main
OPENCLAW_TOKEN=            # from: nemoclaw <sandbox> gateway-token --quiet
```

18790 is the port a NemoClaw sandbox publishes. If the user names OpenClaw's own
18789, they are describing a Gateway running outside a sandbox — ask them to
confirm, because that is not what this build targets.

### 1b. Create one

This needs NemoClaw installed
([their setup walks you through it](https://github.com/NVIDIA/NemoClaw)). The
[`nemoclaw/`](../../nemoclaw/) profile creates the sandbox:

```bash
./nemoclaw/scripts/setup.sh
./nemoclaw/scripts/status.sh
./nemoclaw/scripts/smoke.sh
```

Onboarding changes host and Docker state and can take several minutes. It
onboards against **hosted OpenAI** by default (`NEMOCLAW_PROVIDER=openai`,
default model `gpt-5.4`), reading `OPENAI_API_KEY` from the environment or
`bot/.env` and failing if neither has it. Override `NEMOCLAW_MODEL` for a
different hosted model.

That key is for the *sandbox's* agent model, not for the bot — the bot itself
never calls OpenAI. To serve the sandbox from a local model instead, follow the
[`nemotron-local-llm`](../nemotron-local-llm/SKILL.md) skill; it covers the
provider switch and OpenClaw's 16K-context requirement.

Then wire `bot/.env` as in Step 1a. [`bot/configs/hosted.env`](../../bot/configs/hosted.env)
and [`local.env`](../../bot/configs/local.env) are ready-made.

## Step 2: the voice profile

**Ask: "Hosted voice loop (three API keys, no GPU) or local (everything on your
own DGX, no network)?"**

| `VOICE_PROFILE` | STT | LLM | TTS | Needs |
| --- | --- | --- | --- | --- |
| `hosted` (default) | Deepgram | Nemotron on Baseten | Gradium | `DEEPGRAM_API_KEY`, `BASETEN_API_KEY`, `GRADIUM_API_KEY` |
| `local` | Parakeet | Nemotron | Magpie | Three NIMs, `uv sync --extra nvidia`, a compute-capability-8.0+ GPU |

STT, LLM, and TTS are **not** selected separately. If the user asks to mix — say,
Deepgram with a local Nemotron — tell them the profile is all-or-nothing in this
build.

### Hosted

```dotenv
VOICE_PROFILE=hosted
DEEPGRAM_API_KEY=
BASETEN_API_KEY=
GRADIUM_API_KEY=
```

`BASETEN_MODEL` defaults to `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B`, which
Baseten's shared Model APIs serve by name so a fresh key can call it. Nemotron 3
Nano or Super is a better fit for a latency-sensitive voice loop, but they come
from a dedicated deployment. If the user has one, set both values together from
their Baseten dashboard — the URL alone is not enough:

```dotenv
BASETEN_BASE_URL=https://model-{model_id}.api.baseten.co/environments/production/sync/v1
BASETEN_MODEL=nvidia/NVIDIA-Nemotron-3-Nano
```

### Local

Needs three NIMs: Parakeet ASR, Magpie TTS, and an OpenAI-compatible Nemotron.

```bash
cd bot && uv sync --extra nvidia
```

```dotenv
VOICE_PROFILE=local
NVIDIA_ASR_SERVER=localhost:50051
NVIDIA_TTS_SERVER=localhost:50052
NVIDIA_LLM_BASE_URL=http://localhost:8000/v1
NVIDIA_LLM_MODEL=nvidia/nvidia-nemotron-3-nano
```

Deploying the two **speech** NIMs has real failure modes (an ASR build with no
streaming profile; a NIM that exits with status 0 when VRAM is short), so hand
that to the [`nvidia-riva-speech`](../nvidia-riva-speech/SKILL.md) skill rather
than improvising.

No API key is needed: a local NIM authenticates nothing. Only set
`NVIDIA_API_KEY`, `NVIDIA_ASR_USE_SSL`, `NVIDIA_TTS_USE_SSL`, and
`NVIDIA_TTS_FUNCTION_ID` if they are reaching a remote or NVCF endpoint instead.

## Step 3: run it

```bash
cd bot
uv run agent-voice-bot -t webrtc --port 7860
```

Use `-t eval` for a headless run. If the Gateway is misconfigured the bot still
starts and the voice loop works — delegated requests are where a missing sandbox
surfaces, so test one after it comes up.

## Quick recap

1. **Agent loop:** an OpenClaw NemoClaw sandbox — existing, or created with
   `./nemoclaw/scripts/setup.sh`. Wire `OPENCLAW_GATEWAY_URL` and
   `OPENCLAW_TOKEN`.
2. **Voice profile:** `VOICE_PROFILE=hosted` (three keys) or `local` (three
   NIMs, via the `nvidia-riva-speech` skill for the speech pair).

Everything lands in `bot/.env`.
