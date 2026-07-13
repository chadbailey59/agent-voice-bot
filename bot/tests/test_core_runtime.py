import asyncio
import json

import pytest

from agent_voice_bot.core.models import AgentCapabilities, AgentEvent, AgentRequest, FollowupResult, RunHandle
from agent_voice_bot.core.presentation import DefaultEventPresenter
from agent_voice_bot.core.runtime import collect_result
from agent_voice_bot.features import FeatureRegistry, GuardedRuntime, ObservedRuntime, TelemetryRuntime
from agent_voice_bot.features.telemetry import MemoryTelemetrySink
from agent_voice_bot.nemo import OpenShellObserver
from agent_voice_bot.nemo import JsonlEventSource
from agent_voice_bot.features.telemetry import JsonlTelemetrySink


class Runtime:
    def __init__(self, events=None, capabilities=None):
        self._events = events or [AgentEvent("completed", "done")]
        self.capabilities = capabilities or AgentCapabilities(cancellation=True)
        self.requests = []
        self.followups = []
        self.stops = []
        self.closed = False

    async def start(self, request):
        self.requests.append(request)
        return RunHandle("run-1", "session-1", "fake")

    async def events(self, handle):
        for event in self._events:
            yield event

    async def send_followup(self, handle, text):
        self.followups.append(text)
        return FollowupResult(True, "steered")

    async def stop(self, handle, reason=None):
        self.stops.append(reason)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("events", "summary", "status"),
    [
        ([AgentEvent("text_delta", "hel"), AgentEvent("completed", "hello")], "hello", "completed"),
        ([AgentEvent("cancelled", "stopped")], "stopped", "cancelled"),
        ([AgentEvent("failed", "broken")], "broken", "error"),
    ],
)
async def test_collect_result_terminal_matrix(events, summary, status):
    runtime = Runtime(events)
    result = await collect_result(runtime, await runtime.start(AgentRequest("x", "y")))
    assert (result.summary, result.status) == (summary, status)


@pytest.mark.asyncio
async def test_telemetry_decorator_records_start_and_events():
    sink = MemoryTelemetrySink()
    runtime = TelemetryRuntime(Runtime([AgentEvent("completed", "answer")]), sink)
    result = await collect_result(runtime, await runtime.start(AgentRequest("x", "y")))
    assert result.summary == "answer"
    assert [event.kind for event in sink.events] == ["run_started", "completed"]


class Guard:
    async def check_input(self, request):
        return AgentRequest(request.user_request.upper(), request.reason)

    async def check_output(self, event):
        if event.kind == "progress":
            return None
        return event


@pytest.mark.asyncio
async def test_guardrail_decorator_transforms_input_and_filters_output():
    inner = Runtime([AgentEvent("progress", "noise"), AgentEvent("completed", "safe")])
    runtime = GuardedRuntime(inner, Guard())
    result = await collect_result(runtime, await runtime.start(AgentRequest("hello", "voice")))
    assert inner.requests[0].user_request == "HELLO"
    assert result.summary == "safe"


class Source:
    def __init__(self, payloads):
        self.payloads = payloads
        self.closed = False

    async def events(self, run_id):
        for payload in self.payloads:
            yield payload
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_observed_runtime_merges_openshell_policy_event_before_result():
    source = Source([{"kind": "policy.denied", "message": "network blocked"}])
    inner = Runtime([AgentEvent("progress", "working"), AgentEvent("completed", "done")])
    runtime = ObservedRuntime(inner, [OpenShellObserver(source)])
    handle = await runtime.start(AgentRequest("x", "y"))
    events = [event async for event in runtime.events(handle)]
    assert events[-1].kind == "completed"
    assert any(event.kind == "policy_denied" and event.source == "openshell" for event in events)
    assert runtime.capabilities.approvals is True
    assert runtime.capabilities.cancellation is True


@pytest.mark.asyncio
async def test_presenter_requires_visual_action_for_approval():
    presentation = await DefaultEventPresenter().present(
        AgentEvent("approval_required", "Approve repository write")
    )
    assert presentation.requires_visual_action is True
    assert "screen" in presentation.spoken_text


def test_feature_registry_applies_in_declared_order():
    registry = FeatureRegistry()
    seen = []
    registry.register("one", lambda runtime: seen.append("one") or runtime)
    registry.register("two", lambda runtime: seen.append("two") or runtime)
    result = registry.apply(Runtime(), ("one", "two"))
    assert isinstance(result, Runtime)
    assert seen == ["one", "two"]


def test_feature_registry_rejects_unknown_feature():
    with pytest.raises(ValueError, match="Unsupported AGENT_VOICE_FEATURE"):
        FeatureRegistry().apply(Runtime(), ("missing",))


@pytest.mark.asyncio
async def test_jsonl_nemo_bridge_filters_run_ids_and_writes_telemetry(tmp_path):
    input_path = tmp_path / "events.jsonl"
    input_path.write_text(
        "\n".join(
            [
                json.dumps({"kind": "policy.denied", "run_id": "other", "message": "skip"}),
                json.dumps({"kind": "policy.denied", "run_id": "run-1", "message": "keep"}),
            ]
        )
        + "\n"
    )
    source = JsonlEventSource(input_path, poll_interval=0.001)
    payload = await anext(source.events("run-1"))
    assert payload["message"] == "keep"
    await source.close()

    output_path = tmp_path / "telemetry.jsonl"
    sink = JsonlTelemetrySink(output_path)
    await sink.record(AgentEvent("policy_denied", "keep", run_id="run-1"))
    written = json.loads(output_path.read_text())
    assert written["kind"] == "policy_denied"
    assert written["run_id"] == "run-1"
