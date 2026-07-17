# Skills

Agent skills for setting up this bot and the optional NVIDIA models it can run
locally. They follow the [`vercel-labs/skills`](https://github.com/vercel-labs/skills)
format: one `SKILL.md` per skill, discovered at `skills/<name>/SKILL.md`.

| Skill | Covers |
| --- | --- |
| [`agent-voice-bot-setup`](agent-voice-bot-setup/SKILL.md) | Guided end-to-end setup: choose and wire the agent loop, speech, and voice-loop LLM, and write `bot/.env` |
| [`nvidia-riva-speech`](nvidia-riva-speech/SKILL.md) | Local speech: Parakeet ASR + Magpie TTS on self-hosted Riva NIMs (`SPEECH_PROVIDER=nvidia-riva`) |
| [`nemotron-local-llm`](nemotron-local-llm/SKILL.md) | Local agent-loop inference: Nemotron under Ollama, the partial-offload tag, and the 16K context requirement |

The two NVIDIA skills are optional. The bot's defaults are hosted — Deepgram +
Cartesia for speech, and a hosted OpenAI-compatible endpoint for the agent loop
— and neither is needed to run it. `agent-voice-bot-setup` is the front door and
hands off to the other two when the user chooses a local-GPU path.

## Install them into your coding agent

From the repository root:

```bash
npx skills add .
```

That discovers the skills in this directory and installs them into your
configured agents (for example `.claude/skills/`, project-scoped, or
`~/.claude/skills/` globally). Then ask the agent to set things up:

> Set up the agent voice bot.

> Set up the local NVIDIA speech NIMs for this project.

> Point the agent loop at a local Nemotron under Ollama.

The agent reads the matching skill and walks you through the choices — which
agent loop, hosted or local speech, hosted or local models — then drives the
deploy, the environment wiring, and the failure modes that are easy to
misdiagnose (an ASR NIM that exits with status 0 when VRAM is short, or a
Parakeet build that has no streaming profile).

The local-model paths need an NVIDIA GPU of compute capability 8.0 or higher.
Read a skill yourself before running it if you want to know what will change on
the host: those deploy containers or build local model tags.
