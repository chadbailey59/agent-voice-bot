---
name: agent-voice-bot-setup
description: Guided end-to-end setup for the agent-voice-bot — walk the user through choosing and wiring an agent loop (an existing Hermes/OpenClaw/NemoClaw, a new Nemo sandbox, or direct model inference), then choosing local or hosted STT, LLM, and TTS for the voice bot, and write bot/.env. Use when someone wants to set up, configure, install, or get started running this bot from scratch.
---

# Setting up the agent voice bot

This bot has two independently configured LLM paths plus a speech stack, and
this skill drives all three. Do not guess the user's environment — **ask the
questions below and wire only what they choose.** Confirm each choice before
writing it, and edit `bot/.env` (copied from `bot/.env.example`) as you go.

The three things to settle, in order:

1. **Agent loop** — the delegated background worker. An existing agent, a new
   Nemo sandbox, or direct model inference.
2. **Speech (STT + TTS)** — hosted Deepgram + Cartesia, or local NVIDIA Riva.
3. **Voice loop LLM** — the fast coordinator. Currently OpenAI's Responses API.

Read the root [`README.md`](../../README.md) for the architecture and
[`bot/.env.example`](../../bot/.env.example) for the full variable list.

## Step 0: prerequisites

```bash
cd bot
uv sync --extra dev
cp .env.example .env        # skip if .env already exists — don't clobber it
```

`bot/.env` is gitignored. It needs `OPENAI_API_KEY` for the voice loop no matter
what else is chosen (see Step 3). Never write a key into any file other than
`bot/.env`, and never commit it.

## Step 1: choose the agent loop

**Ask the user first: "Do you already have an agent running — Hermes, OpenClaw,
or a NemoClaw sandbox — or should we set one up?"** Then branch:

### 1a. They already have an agent

Point the bot at it. Pick the mode that matches what they're running and set the
connection variables in `bot/.env`:

| They have | `AGENT_LOOP_MODE` | Connection variables |
| --- | --- | --- |
| A Hermes server | `hermes` | `AGENT_LOOP_HERMES_BASE_URL` (default `http://127.0.0.1:8765`), optional `AGENT_LOOP_HERMES_API_KEY` |
| An OpenClaw Gateway | `openclaw` | `AGENT_LOOP_OPENCLAW_GATEWAY_URL` (e.g. `ws://127.0.0.1:18789`), `AGENT_LOOP_OPENCLAW_TOKEN` |
| A NemoClaw Hermes (`nh`) sandbox | `nemohermes` | `AGENT_LOOP_NEMOHERMES_BASE_URL` (default `http://127.0.0.1:8642/v1`) |
| A NemoClaw Deep Agents (`nd`) sandbox | `deepagents` | `AGENT_LOOP_DEEPAGENTS_SANDBOX` (e.g. `nd`) |

For an existing NemoClaw sandbox, `./nemohermes/scripts/status.sh` and
`./nemodeepagents/scripts/status.sh` confirm it is up before you wire the bot.

### 1b. Set up a new agent

**Ask: "Do you want a full agent framework (tools, sessions, sandboxing), or
just direct model inference (plain chat-completions)?"**

**Direct model inference** — simplest. Set `AGENT_LOOP_MODE=openai` and point it
at any OpenAI-compatible endpoint, local or hosted. Ask local or hosted:

- *Local* (e.g. Ollama): base URL `http://127.0.0.1:11434/v1`, a placeholder
  key, and a model tag the server exposes. If they want a local Nemotron build,
  follow the [`nemotron-local-llm`](../nemotron-local-llm/SKILL.md) skill to
  create the tag first.
  ```dotenv
  AGENT_LOOP_MODE=openai
  AGENT_LOOP_OPENAI_BASE_URL=http://127.0.0.1:11434/v1
  AGENT_LOOP_OPENAI_MODEL=your-local-tag
  AGENT_LOOP_OPENAI_API_KEY=local-placeholder
  AGENT_LOOP_REASONING_EFFORT=high
  ```
- *Hosted*: the provider's exact base URL, model ID, and key. Set the key
  explicitly — it falls back to `OPENAI_API_KEY` only when unset.
  ```dotenv
  AGENT_LOOP_MODE=openai
  AGENT_LOOP_OPENAI_BASE_URL=https://provider.example/v1
  AGENT_LOOP_OPENAI_MODEL=provider-model-id
  AGENT_LOOP_OPENAI_API_KEY=your-provider-key
  AGENT_LOOP_REASONING_EFFORT=high
  ```

**A NemoClaw framework** — creates a sandboxed agent with the extra observability
described in the root README. This needs NemoClaw installed
([their setup walks you through it](https://github.com/NVIDIA/NemoClaw)). **Ask
which runtime:**

| Runtime | Profile | Creates | Bot mode |
| --- | --- | --- | --- |
| OpenClaw (Gateway, live steering) | [`nemoclaw/`](../../nemoclaw/) | `nc` sandbox | `openclaw` |
| Hermes (OpenAI-compatible HTTP) | [`nemohermes/`](../../nemohermes/) | `nh` sandbox | `nemohermes` |
| LangChain Deep Agents Code (headless) | [`nemodeepagents/`](../../nemodeepagents/) | `nd` sandbox | `deepagents` |

Then **ask where that sandbox's model should run — local or hosted:**

- The `nemoclaw` (OpenClaw) and `nemohermes` profiles **onboard against hosted
  OpenAI by default** (`NEMOCLAW_PROVIDER=openai`, default model `gpt-5.4`).
  Their `scripts/setup.sh` reads `OPENAI_API_KEY` from the environment or
  `bot/.env` and fails if neither has it. Override `NEMOCLAW_MODEL` for a
  different hosted model.
- The `nemodeepagents` profile **defaults to local Ollama** and
  `nemotron-3-nano:30b-partial20`. That tag is a local build — create it with
  the [`nemotron-local-llm`](../nemotron-local-llm/SKILL.md) skill before
  onboarding.
- To serve the OpenClaw or Hermes sandbox from a local model instead, follow the
  [`nemotron-local-llm`](../nemotron-local-llm/SKILL.md) skill — it covers the
  provider switch and the OpenClaw 16K-context requirement.

Run the chosen profile's setup, then its checks:

```bash
./nemoclaw/scripts/setup.sh        # or nemohermes / nemodeepagents
./nemoclaw/scripts/status.sh
./nemoclaw/scripts/smoke.sh        # nemohermes and nemodeepagents also ship smoke.sh
```

Onboarding changes host and Docker state and can take several minutes. Each
profile README has the exact bot-side environment (the `bot/configs/*.env` files
are ready-made). Wire the matching `AGENT_LOOP_MODE` and connection variables as
in the table in Step 1a.

**If the user is unsure**, direct model inference against a hosted OpenAI key is
the fastest path to a working bot; recommend that and move on.

## Step 2: choose the speech provider (STT + TTS)

**Ask: "Hosted speech (Deepgram + Cartesia, needs API keys) or local speech on
your own NVIDIA GPU (Parakeet + Magpie)?"**

| `SPEECH_PROVIDER` | STT | TTS | Runs |
| --- | --- | --- | --- |
| `deepgram-cartesia` (default) | Deepgram | Cartesia | Hosted, needs `DEEPGRAM_API_KEY` + `CARTESIA_API_KEY` |
| `nvidia-riva` | Parakeet | Magpie | Local, needs a compute-capability-8.0+ GPU and ~17 GB VRAM |

- **Hosted** is the default and needs nothing more than the two keys in
  `bot/.env`. Optionally set `CARTESIA_VOICE_ID`.
- **Local** requires deploying two Riva NIMs and installing the extra
  (`uv sync --extra nvidia`). This has real failure modes (an ASR NIM that has
  no streaming profile; a NIM that exits with status 0 when VRAM is short), so
  hand it to the [`nvidia-riva-speech`](../nvidia-riva-speech/SKILL.md) skill
  rather than improvising. That skill writes `SPEECH_PROVIDER=nvidia-riva` and
  the `NVIDIA_ASR_SERVER` / `NVIDIA_TTS_SERVER` values.

STT and TTS are not selected separately — `SPEECH_PROVIDER` picks the pair.

## Step 3: the voice loop LLM

The voice loop is the fast coordinator that decides whether to answer directly
or delegate. It currently uses **OpenAI's Responses API**, so `OPENAI_API_KEY`
is required regardless of the agent-loop and speech choices. Optionally override
`VOICE_LOOP_MODEL` (default `gpt-5.4-mini`).

```dotenv
OPENAI_API_KEY=sk-...
# VOICE_LOOP_MODEL=gpt-5.4-mini
```

## Step 4: run it

```bash
cd bot
uv run agent-voice-bot -t webrtc --port 7860
```

Use `-t eval` for a headless run. If an agent-loop backend is misconfigured the
bot still starts and the voice loop works — delegated requests are where a
missing sandbox or endpoint surfaces, so test one after it comes up.

## Quick recap of the decisions

1. **Agent loop:** existing agent → wire its mode; new → NemoClaw framework
   (`nemoclaw`/`nemohermes`/`nemodeepagents`) or direct `openai` inference;
   local or hosted model within that.
2. **Speech:** `deepgram-cartesia` (hosted, keys) or `nvidia-riva` (local, GPU)
   via the `nvidia-riva-speech` skill.
3. **Voice loop:** `OPENAI_API_KEY`, optional `VOICE_LOOP_MODEL`.

Everything lands in `bot/.env`. The related skills —
[`nvidia-riva-speech`](../nvidia-riva-speech/SKILL.md) and
[`nemotron-local-llm`](../nemotron-local-llm/SKILL.md) — handle the local-GPU
paths in depth.
