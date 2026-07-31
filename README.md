Have you ever wished your agent had a voice interface that didn't have to wait
for the entire agent loop to run every time you said anything to it?

Agent Voice Bot is a Pipecat voice frontend for an OpenClaw agent running inside
NVIDIA's [NemoClaw](https://github.com/NVIDIA/NemoClaw).

This is an independently maintained community project. It is not an NVIDIA
product and is not supported by NVIDIA.

## Scope

This branch supports exactly one agent backend and two voice profiles. That is
the whole configuration surface:

- **Agent loop:** OpenClaw, reached through a NemoClaw sandbox's Gateway
  websocket. There is no direct-to-OpenClaw mode, no Hermes, no Deep Agents.
- **Voice loop:** `hosted` or `local`, chosen with `VOICE_PROFILE`. Each picks
  STT, LLM, and TTS together.

| `VOICE_PROFILE` | STT | LLM | TTS | Runs |
| --- | --- | --- | --- | --- |
| `hosted` (default) | Deepgram | Nemotron on Baseten | Gradium | Hosted, needs three API keys |
| `local` | Parakeet | Nemotron | Magpie | On your own DGX, no network |

## Example

[Watch a three-minute example of the voice frontend delegating work to an agent](docs/media/agent-voice-bot-demo.mp4).

## Layout

- [`bot/`](bot/) — the Pipecat voice application and its tests.
- [`nemoclaw/`](nemoclaw/) — the OpenClaw-in-NemoClaw sandbox profile and smoke checks.
- [`skills/`](skills/) — agent skills for setting up the local NVIDIA models.
- [`docs/agent-loop.md`](docs/agent-loop.md) — the agent-loop lifecycle and
  execution policy.

## How the bot works

The bot separates real-time conversation from slower agent work. This is the
main reason it can keep listening and answering quick questions while the agent
is researching, using tools, or changing files in the background.

```text
microphone -> speech-to-text -> voice loop -> text-to-speech -> speaker
                                  |
                                  +-> agent loop -> OpenClaw in NemoClaw
                                                        |
                                  voice loop <- result --+
```

There are two cooperating Pipecat workers, each with a distinct loop:

- **Voice loop.** The `main` worker moves audio through the transport, STT, a
  fast conversational LLM, TTS, and back to the user, maintaining the
  conversation context. For each turn the LLM decides whether to answer
  immediately or call `send_to_agent_loop`. Forwarded work receives a very short
  spoken acknowledgement, leaving the voice loop free to handle another turn. It
  can also call `stop_agent_loop` when the user asks to cancel and
  `end_conversation` when the user says goodbye. Forwarding is fire-and-forget
  over the bus, so the media path never blocks on agent work.
- **Agent loop.** The `agent-loop` worker owns the one active background task
  and its Gateway run handle. When idle, a forwarded message starts a run. When
  busy, another forwarded message steers that run. A completed result is sent
  urgently over the bus, and the voice loop converts it into a concise spoken
  answer.

This split creates two useful concurrent paths: the short, latency-sensitive
voice path and the potentially long-running agent path. A quick question can
therefore stay in the voice path even while agent work is in progress. A
correction intended for that work is forwarded to the agent path instead.

### Follow-ups and cancellation

OpenClaw is the reason this bot only needs one backend: it is the one agent
surface that honours both controls the voice loop offers. `sessions.steer`
redirects a run that is already in flight, and `chat.abort` confirms a
cancellation. Neither is faked — the bot never tells the user a follow-up was
applied or a run was stopped unless the Gateway said so.

Worth knowing what steering actually does, because it is not what the name
suggests: against OpenClaw v2026.5.22 a follow-up does **not** get merged into
the running turn. The Gateway aborts that run and starts a replacement carrying
the new instruction (`interruptedActiveRun: true`). The bot follows the
replacement, so the user hears the answer to what they last asked, and the
spoken acknowledgement says the agent switched to the update rather than
claiming it was added to work already in progress.

## Quick start

You need a NemoClaw sandbox running OpenClaw. If you don't have one,
[NemoClaw's docs walk you through it](https://github.com/NVIDIA/NemoClaw),
including [a starter prompt for Claude Code or Codex](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/home#from-your-coding-agent).

With NemoClaw installed, create and check the sandbox this repo expects:

```bash
./nemoclaw/scripts/setup.sh
./nemoclaw/scripts/status.sh
```

Then run the bot:

```bash
cd bot
cp .env.example .env      # fill in the keys for your profile
uv sync --extra dev
uv run agent-voice-bot -t webrtc --port 7860
```

`.env` is ignored by Git. The hosted profile needs `DEEPGRAM_API_KEY`,
`BASETEN_API_KEY`, and `GRADIUM_API_KEY`. The local profile needs no keys at
all, but does need `uv sync --extra nvidia` and three NIMs — see below.

See [`bot/README.md`](bot/README.md) for every environment variable.

## The hosted profile

`VOICE_PROFILE=hosted` (the default) runs the voice loop on three third-party
APIs and needs no GPU:

- **Deepgram** for streaming STT.
- **Nemotron on [Baseten](https://www.baseten.co/library/nvidia-nemotron-3-nano/)**
  for the voice-loop LLM. The default is the Model APIs slug
  `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B`, because that is the one a fresh
  `BASETEN_API_KEY` can call without further setup. A Nano or Super deployment
  is a better fit for a latency-sensitive voice loop; point `BASETEN_BASE_URL`
  at that deployment's `/sync/v1` URL and set `BASETEN_MODEL` to its served
  model name, both of which come from the Baseten dashboard.
- **Gradium** for streaming TTS.

## The local profile

`VOICE_PROFILE=local` keeps every part of the conversation on your own
hardware, talking to three NIMs you host:

- **Parakeet ASR** over gRPC. Parakeet is the streaming member of NVIDIA's ASR
  family and is built for latency, which is what the voice loop needs; its
  sibling Canary is more accurate but segmented, so it does not stream. Not
  every Parakeet build streams either — `parakeet-0.6b-tdt` ships offline-only
  profiles and cannot serve this pipeline at all.
- **Nemotron** over an OpenAI-compatible NIM endpoint. The voice loop only ever
  decides "answer now" or "hand this to the agent loop", so a Nano-class model
  is the right size here; the heavy reasoning happens in OpenClaw, which
  selects its own model.
- **Magpie TTS** over gRPC.

No API key is involved, because a local NIM authenticates nothing. Each NIM
listens on gRPC 50051 inside its own container, so publish them on different
host ports when they share a machine. Riva binds the acoustic model when the
container starts and the client sends an empty model name, so `NVIDIA_ASR_MODEL`
and `NVIDIA_TTS_MODEL` only label metrics — redeploy the NIM to change models.

Deploying the speech NIMs, picking a Parakeet build that can actually stream,
and changing voices are covered by the
[`nvidia-riva-speech`](skills/nvidia-riva-speech/SKILL.md) skill:

```bash
npx skills add .    # installs the skills into your coding agent
```

Then ask your agent to "set up the local NVIDIA speech NIMs for this project".
See [`skills/README.md`](skills/README.md).

## Verification

The test suite is deterministic and needs no live speech, model, or agent
credentials. The OpenClaw tests run a real websocket server in-process rather
than mocking the connection, since the handshake and request correlation are
the parts most likely to break.

```bash
cd bot
uv sync --extra dev
uv run pytest
```

Add `--extra nvidia` to also exercise the local profile; without it those tests
skip.

## Support and compatibility

NemoClaw is evolving quickly. The checked-in profile documents the commands and
runtime boundaries it exercises, but it is not a compatibility guarantee for
every NemoClaw, OpenShell, Pipecat, or OpenClaw release. Please open an issue
with the host platform, component versions, selected profile, and failing
command when reporting a reproducible problem.

## License

Licensed under the [Apache License 2.0](LICENSE).
