"""Input/output guardrail decorator independent of any guardrail vendor."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from agent_voice_bot.core.models import (
    AgentCapabilities,
    AgentEvent,
    AgentRequest,
    FollowupResult,
    RunHandle,
)
from agent_voice_bot.core.runtime import AgentRuntime


class Guardrail(Protocol):
    async def check_input(self, request: AgentRequest) -> AgentRequest: ...
    async def check_output(self, event: AgentEvent) -> AgentEvent | None: ...


class GuardedRuntime:
    def __init__(self, runtime: AgentRuntime, guardrail: Guardrail):
        self.runtime = runtime
        self.guardrail = guardrail

    @property
    def capabilities(self) -> AgentCapabilities:
        return self.runtime.capabilities

    async def start(self, request: AgentRequest) -> RunHandle:
        return await self.runtime.start(await self.guardrail.check_input(request))

    async def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]:
        async for event in self.runtime.events(handle):
            checked = await self.guardrail.check_output(event)
            if checked is not None:
                yield checked

    async def send_followup(self, handle: RunHandle, user_input: str) -> FollowupResult:
        checked = await self.guardrail.check_input(AgentRequest(user_input, "follow-up"))
        return await self.runtime.send_followup(handle, checked.user_request)

    async def stop(self, handle: RunHandle, reason: str | None = None) -> None:
        await self.runtime.stop(handle, reason)

    async def close(self) -> None:
        await self.runtime.close()
