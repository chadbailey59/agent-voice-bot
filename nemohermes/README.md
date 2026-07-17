# NemoHermes local profile

`nemohermes` is the Hermes-selected alias of `nemoclaw`. This profile uses the
existing `nh` sandbox and its forwarded OpenAI-compatible API on port 8642.

```bash
./scripts/status.sh
./scripts/smoke.sh
```

To create the sandbox on a new machine, run `./scripts/setup.sh`. It onboards
against hosted OpenAI (`openai-api` at `https://api.openai.com/v1`) and defaults
to `gpt-5.4`; override `NEMOCLAW_MODEL` to pick another model. The script reads
`OPENAI_API_KEY` from the environment, falling back to `bot/.env`, and fails if
neither has it. The key is never written into this profile.

Configure the bot with:

```bash
cd ../bot
export AGENT_LOOP_MODE=nemohermes
export AGENT_LOOP_NEMOHERMES_BASE_URL=http://127.0.0.1:8642/v1
export AGENT_LOOP_NEMOHERMES_MODEL=hermes-agent
uv run agent-voice-bot -t webrtc --port 7860
```
