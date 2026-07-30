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
    async def start(user_input: str) -> RunHandle: ...
    def events(handle: RunHandle) -> AsyncIterator[AgentEvent]: ...
    async def send_followup(handle: RunHandle, text: str) -> FollowupResult: ...
    async def stop(handle: RunHandle, reason: str | None = None) -> None: ...
```

`AgentEvent` normalizes `text_delta`, `completed`, `cancelled`, and `failed`.
The voice UI speaks only concise acknowledgements and terminal results.

An earlier revision also carried an `AgentCapabilities` record — `streaming`,
`steering`, `cancellation`, `session_continuation` — so the worker could tell
the user when a backend could not honour a control. With OpenClaw as the only
backend all four are unconditionally true, nothing branched on them, and the
record described nothing. It was removed. Reintroduce it if and when a
lesser-capability backend returns, because the honesty rule below still stands.

The protocol survives having one implementation because it is the seam that
keeps Pipecat frames, bus jobs, and media timing out of the Gateway client —
and the Gateway's websocket details out of the worker.

Every run must end in a terminal event. A backend whose transport can vanish
mid-run (a dropped websocket, a killed process) has to synthesize `failed`
rather than leave the consumer waiting, or the worker stays wedged with an
active job that can only be cleared by an explicit stop.

## Execution policy

There is at most one active agent run per voice conversation.

- Idle + forwarded input: call `start` and consume `events` in the background.
- Busy + forwarded input: call `send_followup` on the active handle.
- Stop request: call `stop`, cancel the Pipecat bus job, and keep the voice loop
  responsive.
- Disconnect: cancel outstanding work and release backend connections.

Never report that a follow-up was steered or a run was cancelled unless the
backend confirmed it.

A handle carries the run identifier, which scopes cancellation and event
correlation, plus whatever the backend needs to steer that run. Conversational
continuity is a separate concept: here it lives in the configured OpenClaw
session key, which is stable across runs and therefore not per-handle state.

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

The forwarded message carries `AGENT_LOOP_INSTRUCTION` appended to the user's
words. That instruction is not decoration: the agent's reply is spoken aloud, so
it must come back as one short plain-text answer rather than the formatted,
question-ending output a coding agent produces by default. Keep it in one place
so it cannot be built somewhere and dropped at the boundary.

## Implemented module boundaries

`core.py` holds these contracts and imports neither Pipecat nor websockets.
`openclaw.py` is the Gateway client, `voice.py` builds the media services, and
`bot.py`/`agent_worker.py` are the two Pipecat workers.
