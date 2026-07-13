# NemoClaw / OpenClaw local profile

This profile creates a named NemoClaw sandbox running the OpenClaw harness. It
is separate from the `nh` Hermes sandbox, and defaults to dashboard port 18790.

```bash
NEMOCLAW_SANDBOX_NAME=nc ./scripts/setup.sh
./scripts/status.sh
```

The setup registers the already-running Ollama server as a custom
OpenAI-compatible endpoint at `http://127.0.0.1:11434/v1` for onboarding,
avoiding systemd or sudo changes. After creation it switches runtime traffic to
the authenticated `ollama-local` provider already created by the NemoHermes
profile. Set up NemoHermes first on a new machine. The default model is
`nemotron-3-nano:30b-partial20`; override `NEMOCLAW_ENDPOINT_URL` or
`NEMOCLAW_MODEL` before running it. Onboarding changes host and Docker state and
may take several minutes.

The local OpenClaw tool catalog requires more than an 8K context once output
tokens are reserved. Recreate the shared partial-offload tag with the checked-in
16K definition before onboarding or rebuilding:

```bash
ollama create nemotron-3-nano:30b-partial20 \
  -f ollama/nemotron-3-nano-partial20.Modelfile
```

The setup script bakes matching `contextWindow=16384` and `maxTokens=4096`
metadata into OpenClaw. An 8K runtime cannot accommodate OpenClaw's roughly
7.6K-token bootstrap/tool prompt after reserving output tokens.

Configure the bot with the sandbox's forwarded Gateway:

```bash
cd ../bot
export AGENT_LOOP_MODE=openclaw
export AGENT_LOOP_OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18790
export AGENT_LOOP_OPENCLAW_SESSION_KEY=agent:main:main
export AGENT_LOOP_OPENCLAW_TOKEN="$(nemoclaw nc gateway-token --quiet)"
uv run agent-voice-bot -t webrtc --port 7860
```
