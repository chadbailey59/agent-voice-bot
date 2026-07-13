import asyncio

import pytest

from agent_voice_bot.agent_loop import AgentLoopClient, AgentLoopRequest
from agent_voice_bot.config import AgentLoopConfig
from agent_voice_bot.features import ObservedRuntime, TelemetryRuntime
from agent_voice_bot.features.telemetry import MemoryTelemetrySink
from agent_voice_bot.nemo import OpenShellObserver


class PolicySource:
    async def events(self, run_id):
        yield {"kind": "tool.started", "message": "browser search"}
        yield {"kind": "policy.denied", "message": "blocked example.invalid"}
        await asyncio.Event().wait()

    async def close(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("nemo_features", [False, True])
async def test_complete_mock_session_direct_and_nemo_enhanced(nemo_features):
    base = AgentLoopClient(
        AgentLoopConfig(mode="mock", mock_delay_secs=0, mock_result="E2E-2048")
    )
    sink = MemoryTelemetrySink()
    runtime = base
    if nemo_features:
        runtime = ObservedRuntime(runtime, [OpenShellObserver(PolicySource())])
        runtime = TelemetryRuntime(runtime, sink)

    handle = await runtime.start(AgentLoopRequest("research a topic", "voice"))
    events = []
    async for event in runtime.events(handle):
        events.append(event)
        if event.kind in {"completed", "failed", "cancelled"}:
            break

    assert events[-1].kind == "completed"
    assert "E2E-2048" in events[-1].text
    if nemo_features:
        assert {"tool_started", "policy_denied", "completed"} <= {e.kind for e in events}
        assert sink.events[0].kind == "run_started"
    else:
        assert [event.kind for event in events] == ["completed"]


@pytest.mark.asyncio
async def test_mock_runtime_can_be_cancelled_end_to_end():
    runtime = AgentLoopClient(AgentLoopConfig(mode="mock", mock_delay_secs=30))
    handle = await runtime.start(AgentLoopRequest("slow task", "voice"))
    await runtime.stop(handle, "user cancelled")
    task = handle.metadata["task"]
    assert task.cancelled()
