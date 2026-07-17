# NemoClaw / OpenClaw local profile

This profile creates a named NemoClaw sandbox running the OpenClaw harness. It
is separate from the `nh` Hermes sandbox, and defaults to dashboard port 18790.

```bash
NEMOCLAW_SANDBOX_NAME=nc ./scripts/setup.sh
./scripts/status.sh
```

The setup onboards against hosted OpenAI: it registers the `openai-api` provider
at `https://api.openai.com/v1` and routes runtime traffic straight to it, so no
local Ollama, systemd, or NemoHermes provider is required first. The default
model is `gpt-5.4`; override `NEMOCLAW_MODEL` before running it. Onboarding
changes Docker state and may take several minutes.

The script reads `OPENAI_API_KEY` from the environment, falling back to
`bot/.env`, and fails if neither has it. The key is never written into this
profile — keep it in `bot/.env` or your shell.

Inference is now billed per token against your OpenAI account rather than run
locally, so the sandbox no longer needs the partial-offload tag or the 16K
context workaround the local nemotron build required. Onboarding uses the stock
`contextWindow=131072` / `maxTokens=4096` metadata, which clears OpenClaw's
roughly 7.6K-token bootstrap/tool prompt with room to spare.

Configure the bot with the sandbox's forwarded Gateway:

```bash
cd ../bot
export AGENT_LOOP_MODE=openclaw
export AGENT_LOOP_OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18790
export AGENT_LOOP_OPENCLAW_SESSION_KEY=agent:main:main
export AGENT_LOOP_OPENCLAW_TOKEN="$(nemoclaw nc gateway-token --quiet)"
uv run agent-voice-bot -t webrtc --port 7860
```
