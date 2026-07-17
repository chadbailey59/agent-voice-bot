---
name: nemotron-local-llm
description: Run the Nemotron LLM locally under Ollama for agent-voice-bot's agent loop — building the nemotron-3-nano partial-offload tag, the 16K context requirement for OpenClaw, and pointing the bot or a Nemo sandbox at loopback Ollama. Use when serving the agent loop from a local model instead of a hosted provider.
---

# Local Nemotron under Ollama

The bot uses LLMs in two places, configured separately. This skill covers the
**agent loop** — the delegated work — running against a local Nemotron build
served by Ollama's OpenAI-compatible API. The **voice loop** is a separate,
latency-sensitive coordinator (currently OpenAI's Responses API,
`VOICE_LOOP_MODEL`, default `gpt-5.4-mini`) and is not affected by anything
here.

Local inference is free and keeps work on the machine, but a 30B model shares
the GPU with anything else on it. If you also run the Riva speech NIMs (~17 GB),
check the VRAM budget first — see the `nvidia-riva-speech` skill.

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

## Point the bot's agent loop straight at Ollama

The simplest local setup. This is chat-completion inference only, not the tools
or session controls of a full agent framework:

```dotenv
AGENT_LOOP_MODE=openai
AGENT_LOOP_OPENAI_BASE_URL=http://127.0.0.1:11434/v1
AGENT_LOOP_OPENAI_MODEL=nemotron-3-nano:30b-partial20
AGENT_LOOP_OPENAI_API_KEY=local-placeholder
AGENT_LOOP_REASONING_EFFORT=high
```

The API key may be omitted when the local endpoint does not require one. The
model name must match a tag the server actually exposes. Keep
`AGENT_LOOP_TIMEOUT_SECS` high enough for local generation speed.

## Behind a Nemo sandbox instead

When `AGENT_LOOP_MODE` is `hermes`, `openclaw`, `nemohermes`, or `deepagents`,
the framework chooses the model, not the bot. Configure inference in the
framework first, then point the bot at the resulting endpoint.

Of the checked-in profiles, only [`nemodeepagents/`](../../nemodeepagents/)
still defaults to local Ollama and `nemotron-3-nano:30b-partial20`; set
`NEMOCLAW_MODEL` to choose another model. The `nemoclaw/` and `nemohermes/`
profiles now onboard against hosted OpenAI (`NEMOCLAW_PROVIDER=openai`), so
pointing those at local Nemotron means editing their `scripts/setup.sh` to set
`NEMOCLAW_PROVIDER=ollama` and a local `NEMOCLAW_MODEL`, or running the guided
setup instead:

```bash
nemoclaw onboard --agent openclaw          # or --agent langchain-deepagents-code
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
