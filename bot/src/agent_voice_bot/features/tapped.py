"""Records the complete normalized runtime stream."""

from __future__ import annotations

from typing import AsyncIterator

from agent_voice_bot.core.models import AgentCapabilities, AgentEvent, AgentRequest, FollowupResult, RunHandle
from agent_voice_bot.core.runtime import AgentRuntime
from agent_voice_bot.features.telemetry import TelemetrySink


class TelemetryRuntime:
    def __init__(self, runtime: AgentRuntime, sink: TelemetrySink):
        self.runtime = runtime
        self.sink = sink

    @property
    def capabilities(self) -> AgentCapabilities:
        return self.runtime.capabilities

    async def start(self, request: AgentRequest) -> RunHandle:
        handle = await self.runtime.start(request)
        await self.sink.record(AgentEvent("run_started", source="runtime", run_id=handle.run_id))
        return handle

    async def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]:
        async for event in self.runtime.events(handle):
            await self.sink.record(event)
            yield event

    async def send_followup(self, handle: RunHandle, user_input: str) -> FollowupResult:
        return await self.runtime.send_followup(handle, user_input)

    async def stop(self, handle: RunHandle, reason: str | None = None) -> None:
        await self.runtime.stop(handle, reason)

    async def close(self) -> None:
        await self.runtime.close()
