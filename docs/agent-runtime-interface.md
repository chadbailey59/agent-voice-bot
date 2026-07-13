# Agent runtime interface

## Decision

Keep the Pipecat voice loop independent from the agent harness. Integrate an
agent through a small, capability-described, evented session interface rather
than treating every harness as an LLM chat-completions provider.

The voice path stays live while agent work runs in another Pipecat worker:

```text
microphone -> STT -> voice loop -> TTS -> speaker
                         |
                         +-> agent session worker -> NemoClaw harness
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
    async def events(handle: RunHandle) -> AsyncIterator[AgentEvent]: ...
    async def follow_up(handle: RunHandle, text: str) -> FollowUpResult: ...
    async def cancel(handle: RunHandle, reason: str | None = None) -> None: ...
```

`AgentCapabilities` should explicitly report:

- `streaming`: partial output or progress events are available.
- `steering`: an active run accepts refinements.
- `cancellation`: the backend can stop active work.
- `session_continuation`: later turns can reuse agent state.

`AgentEvent` should normalize `started`, `progress`, `text_delta`, `tool_start`,
`tool_end`, `completed`, `cancelled`, and `failed`. The voice UI should speak
only concise acknowledgements and terminal results by default; progress can
drive visual state without creating audio chatter.

## Execution policy

There is at most one active agent run per voice conversation.

- Idle + forwarded input: call `start` and consume `events` in the background.
- Busy + forwarded input with steering: call `follow_up` on the active handle.
- Busy + forwarded input without steering: report that the update was not
  applied. A future configurable policy may cancel-and-restart, but it must not
  silently discard completed work or pretend the refinement was accepted.
- Stop request: call `cancel`, cancel the Pipecat bus job, and keep the voice
  loop responsive.
- Disconnect: cancel outstanding work and release backend connections.

Each handle carries both a run identifier and a stable session identifier.
Run identifiers scope cancellation and event correlation; session identifiers
scope conversational continuity. Do not collapse the two concepts.

## NemoClaw mappings

### OpenClaw harness (`nemoclaw` profile)

Use the OpenClaw Gateway WebSocket as the native control plane:

- start: `chat.send`
- events: Gateway `chat` events
- follow-up: `sessions.steer`
- cancel: `chat.abort`
- continuity: stable OpenClaw session key

This is the full-capability adapter and the reference behavior for the
interface.

### Hermes harness (`nemohermes` profile)

Use the forwarded OpenAI-compatible API at `/v1/chat/completions`. Preserve the
`X-Hermes-Session-Id` response header and send it on later turns when supported,
so HTTP requests continue the same Hermes session.

The public compatibility endpoint is request/response oriented. Until Hermes
publishes a run-control API, advertise no live steering and no guaranteed
server-side cancellation. Cancelling the local HTTP request is still useful for
latency and resource cleanup, but must not be presented as confirmed agent
preemption.

## Upstream packaging

For `nemoclaw-community`, package this as an example with the bot isolated in
its own Python project, profile setup scripts, an `.env.example`, eval scenarios,
and a short architecture document. Do not vendor NemoClaw or Hermes source.
Install them through the maintained NemoClaw installer and treat their exposed
gateway/API contracts as dependencies.

## Implemented package boundaries

The Python workspace implements these contracts under `agent_voice_bot/core`,
with direct runtime construction in `runtimes`, injected speech/voice providers
in `services`, decorators in `features`, and one-way optional Nemo dependencies
under `nemo`. Core modules never import the Nemo package. OpenShell integration
uses a JSONL event-source boundary so the collector can evolve independently of
the real-time media process.
