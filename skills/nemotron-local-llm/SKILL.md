---
name: nemotron-local-llm
description: Serve the OpenClaw agent loop from a local Nemotron under Ollama instead of a hosted provider — building the nemotron-3-nano partial-offload tag, the 16K context requirement OpenClaw imposes, and pointing a NemoClaw sandbox at loopback Ollama. Use when the NemoClaw sandbox's model should run locally.
---

# Local Nemotron under Ollama

The bot uses LLMs in two places, configured separately. This skill covers the
**agent loop** — the OpenClaw agent inside the NemoClaw sandbox — running against
a local Nemotron build served by Ollama's OpenAI-compatible API. The bot never
configures that model itself; NemoClaw does, and the bot only sees the Gateway.

The **voice loop** is a separate, latency-sensitive coordinator selected by
`VOICE_PROFILE` and is not affected by anything here. If the goal is a local
*voice* loop, that is `VOICE_PROFILE=local`, which uses NIMs rather than Ollama —
see the [`nvidia-riva-speech`](../nvidia-riva-speech/SKILL.md) skill and
[`bot/README.md`](../../bot/README.md).

Local inference is free and keeps work on the machine, but a 30B model shares
the GPU with anything else on it. If you also run the Riva speech NIMs (~17 GB)
and a Nemotron voice NIM, check the VRAM budget first.

## Build the partial-offload tag

Two settings matter — a 16K context and partial GPU offload (`num_gpu 20`),
which is what lets a 30B model share a card. Create the tag from an inline
Modelfile:

```bash
ollama create nemotron-3-nano:30b-partial20 -f - <<'EOF'
FROM nemotron-3-nano:30b
PARAMETER num_ctx 16384
PARAMETER num_gpu 20
PARAMETER temperature 1
PARAMETER top_p 1
EOF
```

Tune `num_gpu` to the card: raise it to offload more layers when VRAM is free,
lower it when the GPU is shared. Verify with `ollama list` and `ollama ps`.

## The 16K context is not optional for OpenClaw

**An 8K runtime cannot run OpenClaw against this model.** The local OpenClaw
tool catalog needs more than 8K once output tokens are reserved: its
bootstrap/tool prompt is roughly 7.6K tokens, and reserving 4K of output leaves
nothing. Recreate the tag with the 16K definition above before onboarding or
rebuilding an OpenClaw sandbox, and bake matching metadata into OpenClaw
(`contextWindow=16384`, `maxTokens=4096`).

Hosted providers do not have this constraint — a stock `contextWindow=131072`
clears the same prompt with room to spare.

## Point the sandbox at local Ollama

The [`nemoclaw/`](../../nemoclaw/) profile onboards against hosted OpenAI
(`NEMOCLAW_PROVIDER=openai`). Pointing it at local Nemotron means editing its
`scripts/setup.sh` to set `NEMOCLAW_PROVIDER=ollama` and a local
`NEMOCLAW_MODEL`, or running the guided setup instead:

```bash
nemoclaw onboard --agent openclaw
```

### Gotcha: onboarding validation vs. runtime traffic

Onboarding an OpenClaw sandbox against loopback Ollama has a two-step shape
worth knowing. Registering Ollama as a **custom OpenAI-compatible endpoint** at
`http://127.0.0.1:11434/v1` lets onboarding validate without rewriting the
Ollama systemd unit or needing sudo. But runtime traffic then has to be switched
to an authenticated host proxy provider:

```bash
nemoclaw inference set \
  --provider ollama-local \
  --model nemotron-3-nano:30b-partial20 \
  --sandbox "$sandbox" \
  --no-verify
nemoclaw "$sandbox" recover
```

If the `ollama-local` provider does not exist, runtime inference will not reach
loopback Ollama even though onboarding succeeded.

Onboarding changes host and Docker state and may take several minutes.

## Bot-side settings

Nothing about the model appears in `bot/.env` — only the Gateway does. A local
model is slower than a hosted one, so raise the bot's patience:

```dotenv
OPENCLAW_TIMEOUT_SECS=600
```
