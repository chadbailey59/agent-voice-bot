# The agent loop

## Decision

Keep the Pipecat voice loop independent from the agent harness. Drive the agent
through a small evented session lifecycle rather than treating the harness as an
LLM chat-completions provider.

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

## Lifecycle

`OpenClawRuntime` exposes four operations, and the worker drives them in this
order:

```python
async def start(user_input: str) -> RunHandle
def events(handle: RunHandle) -> AsyncIterator[AgentEvent]
async def send_followup(handle: RunHandle, text: str) -> FollowupResult
async def stop(handle: RunHandle, reason: str | None = None) -> None
```

`AgentEvent` normalizes `text_delta`, `completed`, `cancelled`, and `failed`.
`collect_result` folds that stream into the single answer the user hears. The
voice UI speaks only concise acknowledgements and terminal results.

Every run must end in a terminal event. A transport that can vanish mid-run — a
dropped websocket, a killed process — has to synthesize `failed` rather than
leave the consumer waiting, or the worker stays wedged with an active job that
only an explicit stop can clear.

### What used to be here

Two abstractions guarded the multi-backend era and are gone:

- An `AgentCapabilities` record (`streaming`, `steering`, `cancellation`,
  `session_continuation`) let the worker tell the user when a backend could not
  honour a control. With OpenClaw all four are unconditionally true, nothing
  branched on them, and the record described nothing.
- An `AgentRuntime` Protocol declared the four operations above. With one
  implementation it named a substitutability that did not exist.

Both are recoverable from git history. Restore them together if a second, lesser
backend ever returns — the honesty rule below is what they existed to enforce,
and it still stands whether or not a type is checking it.

The boundary they were guarding is still real, and is now maintained by module
discipline instead: `openclaw.py` must not import Pipecat. The worker adapts
runs, events, and results into bus messages; keeping that direction one-way is
what lets the Gateway client be tested without media timing.

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

`openclaw.py` holds the run/event/result types and the Gateway client, and
imports no Pipecat. `voice.py` builds the media services, and
`bot.py`/`agent_worker.py` are the two Pipecat workers.
