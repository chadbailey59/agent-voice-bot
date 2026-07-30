# Agent runtime interface

## Decision

Keep the Pipecat voice loop independent from the agent harness. Integrate the
agent through a small, capability-described, evented session interface rather
than treating the harness as an LLM chat-completions provider.

The voice path stays live while agent work runs in another Pipecat worker:

```text
microphone -> STT -> voice loop -> TTS -> speaker
                         |
                         +-> agent session worker -> OpenClaw in NemoClaw
                                      |
                                      +-> progress/final events -> voice loop
```

The voice model has only two agent controls:

1. `send_to_agent_loop(input)` starts work or forwards a refinement.
2. `stop_agent_loop(reason)` requests preemptive cancellation.

It does not select backend methods or decide whether a busy agent can be
steered. That policy belongs to the agent session worker.

## Contract

```python
class AgentRuntime(Protocol):
    capabilities: AgentCapabilities

    async def start(request: AgentRequest) -> RunHandle: ...
    def events(handle: RunHandle) -> AsyncIterator[AgentEvent]: ...
    async def send_followup(handle: RunHandle, text: str) -> FollowupResult: ...
    async def stop(handle: RunHandle, reason: str | None = None) -> None: ...
    async def close() -> None: ...
```

`AgentCapabilities` explicitly reports:

- `streaming`: partial output or progress events are available.
- `steering`: an active run accepts refinements.
- `cancellation`: the backend can stop active work.
- `session_continuation`: later turns can reuse agent state.

`AgentEvent` normalizes `run_started`, `progress`, `text_delta`, `tool_started`,
`tool_finished`, `completed`, `cancelled`, and `failed`. The voice UI speaks
only concise acknowledgements and terminal results by default; progress can
drive visual state without creating audio chatter.

The protocol survives having one implementation because it is the seam that
keeps Pipecat frames, bus jobs, and media timing out of the Gateway client —
and the Gateway's websocket details out of the worker.

## Execution policy

There is at most one active agent run per voice conversation.

- Idle + forwarded input: call `start` and consume `events` in the background.
- Busy + forwarded input: call `send_followup` on the active handle.
- Stop request: call `stop`, cancel the Pipecat bus job, and keep the voice loop
  responsive.
- Disconnect: cancel outstanding work and release backend connections.

Never report that a follow-up was steered or a run was cancelled unless the
backend confirmed it.

Each handle carries both a run identifier and a stable session identifier.
Run identifiers scope cancellation and event correlation; session identifiers
scope conversational continuity. Do not collapse the two concepts.

## OpenClaw mapping

The OpenClaw Gateway websocket is the native control plane:

- start: `chat.send`
- events: Gateway `chat` frames, filtered to this run's `runId`
- follow-up: `sessions.steer`
- cancel: `chat.abort`
- continuity: stable OpenClaw session key

This is a full-capability adapter: streaming, steering, cancellation, and
session continuation are all real, which is why it is the only backend the bot
carries. Adapters for request/response agent APIs had to advertise no live
steering and no confirmed server-side cancellation, and every one of them made
the voice loop's two controls partly dishonest.

## Implemented package boundaries

The Python workspace implements these contracts under `agent_voice_bot/core`,
with the Gateway client in `runtimes/openclaw.py` and the voice-service profiles
in `services/profiles.py`. `core/` imports neither Pipecat nor websockets.
