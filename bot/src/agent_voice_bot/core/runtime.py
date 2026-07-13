"""Agent runtime protocol and lifecycle helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Protocol, runtime_checkable

from agent_voice_bot.core.models import (
    AgentCapabilities,
    AgentEvent,
    AgentRequest,
    AgentResult,
    FollowupResult,
    RunHandle,
)


@runtime_checkable
class AgentRuntime(Protocol):
    @property
    def capabilities(self) -> AgentCapabilities: ...
    async def start(self, request: AgentRequest) -> RunHandle: ...
    def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]: ...
    async def send_followup(self, handle: RunHandle, user_input: str) -> FollowupResult: ...
    async def stop(self, handle: RunHandle, reason: str | None = None) -> None: ...
    async def close(self) -> None: ...


class BaseAgentRuntime(ABC):
    capabilities = AgentCapabilities()

    async def run(self, request: AgentRequest) -> AgentResult:
        return await collect_result(self, await self.start(request))

    @abstractmethod
    async def start(self, request: AgentRequest) -> RunHandle: ...

    @abstractmethod
    async def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]:
        if False:
            yield AgentEvent("progress")

    async def send_followup(self, handle: RunHandle, user_input: str) -> FollowupResult:
        return FollowupResult(False, "Runtime does not support live follow-up.")

    async def stop(self, handle: RunHandle, reason: str | None = None) -> None:
        return None

    async def close(self) -> None:
        return None


async def collect_result(runtime: AgentRuntime, handle: RunHandle) -> AgentResult:
    parts: list[str] = []
    async for event in runtime.events(handle):
        if event.kind == "text_delta" and event.text:
            parts.append(event.text)
        elif event.kind == "completed":
            return AgentResult(event.text or "".join(parts).strip(), raw=event.raw)
        elif event.kind == "cancelled":
            return AgentResult(event.text or "The agent run was cancelled.", "cancelled", event.raw)
        elif event.kind == "failed":
            return AgentResult(event.text or "The agent run failed.", "error", event.raw)
    return AgentResult("The agent run ended without a final response.")
