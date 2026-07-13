# NemoClaw / LangChain Deep Agents Code local profile

This profile creates a dedicated NemoClaw sandbox for LangChain Deep Agents
Code. Deep Agents Code is a terminal runtime: it has no dashboard or agent
gateway. Agent Voice Bot runs one headless `dcode -n` task per delegated voice
request through `nemoclaw <sandbox> exec`.

Install NemoClaw v0.0.76 or newer (v0.0.79 or newer is recommended), then create
the sandbox:

```bash
NEMOCLAW_SANDBOX_NAME=nd ./scripts/setup.sh
./scripts/status.sh
./scripts/smoke.sh
```

The setup uses the canonical `langchain-deepagents-code` agent ID and the same
local Ollama defaults as the other checked-in profiles. The default model is
`nemotron-3-nano:30b-partial20`; set `NEMOCLAW_MODEL` to choose another model.
Onboarding changes host and Docker state and can take several minutes. Current
NemoClaw releases install and validate their managed, pinned Deep Agents Code
package while building the sandbox.

To use a hosted provider or a different local inference route, run the guided
NemoClaw setup instead:

```bash
nemo-deepagents onboard
# Equivalent canonical form:
nemoclaw onboard --agent langchain-deepagents-code
```

Once the smoke task succeeds, start the voice bot from `bot/`:

```bash
set -a
source configs/nemoclaw-deepagents.env
set +a
uv run agent-voice-bot -t webrtc --port 7860
```

The `deepagents` adapter supports cancelling the local headless process. Deep
Agents Code does not expose the gateway APIs needed for live steering or
continuing a headless session, so the bot does not advertise those capabilities.

References:

- [NemoClaw Quickstart with LangChain Deep Agents Code](https://docs.nvidia.com/nemoclaw/latest/user-guide/deepagents/get-started/quickstart)
- [LangChain Deep Agents Code overview](https://docs.langchain.com/oss/python/deepagents/code/overview)

