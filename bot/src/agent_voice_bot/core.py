"""The seam between the voice application and the agent backend.

This module knows nothing about Pipecat, websockets, or OpenClaw. It exists so
the bus worker can drive a run without holding a Gateway connection's details,
and so the Gateway client can be tested without media timing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

EventKind = Literal["text_delta", "completed", "cancelled", "failed"]


@dataclass(frozen=True)
class RunHandle:
    """One in-flight agent run, plus whatever the backend needs to steer it."""

    run_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentEvent:
    kind: EventKind
    text: str = ""
    run_id: str | None = None


@dataclass(frozen=True)
class AgentResult:
    summary: str
    status: Literal["completed", "cancelled", "error"] = "completed"


@dataclass(frozen=True)
class FollowupResult:
    applied: bool
    status: str


@runtime_checkable
class AgentRuntime(Protocol):
    async def start(self, user_input: str) -> RunHandle: ...
    def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]: ...
    async def send_followup(self, handle: RunHandle, user_input: str) -> FollowupResult: ...
    async def stop(self, handle: RunHandle, reason: str | None = None) -> None: ...


async def collect_result(runtime: AgentRuntime, handle: RunHandle) -> AgentResult:
    parts: list[str] = []
    async for event in runtime.events(handle):
        if event.kind == "text_delta" and event.text:
            parts.append(event.text)
        elif event.kind == "completed":
            return AgentResult(event.text or "".join(parts).strip())
        elif event.kind == "cancelled":
            return AgentResult(event.text or "The agent run was cancelled.", "cancelled")
        elif event.kind == "failed":
            return AgentResult(event.text or "The agent run failed.", "error")
    return AgentResult("The agent run ended without a final response.")
