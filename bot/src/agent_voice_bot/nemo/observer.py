"""Normalizes OpenShell control-plane events into core session events."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from agent_voice_bot.core.models import AgentCapabilities, AgentEvent, RunHandle
from agent_voice_bot.features.telemetry import TelemetrySink


class OpenShellEventSource(Protocol):
    def events(self, run_id: str) -> AsyncIterator[dict[str, Any]]: ...
    async def close(self) -> None: ...


class OpenShellObserver:
    capabilities = AgentCapabilities(approvals=True, tool_events=True)

    def __init__(self, source: OpenShellEventSource, telemetry: TelemetrySink | None = None):
        self.source = source
        self.telemetry = telemetry

    async def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]:
        async for payload in self.source.events(handle.run_id):
            event = self._normalize(handle, payload)
            if event is None:
                continue
            if self.telemetry:
                await self.telemetry.record(event)
            yield event

    def _normalize(self, handle: RunHandle, payload: dict[str, Any]) -> AgentEvent | None:
        kind = str(payload.get("kind") or payload.get("event") or "")
        mapping = {
            "policy.denied": "policy_denied",
            "approval.required": "approval_required",
            "approval.resolved": "approval_resolved",
            "sandbox.unhealthy": "sandbox_unhealthy",
            "tool.started": "tool_started",
            "tool.finished": "tool_finished",
        }
        normalized = mapping.get(kind)
        if normalized is None:
            return None
        return AgentEvent(
            normalized,
            text=str(payload.get("message") or payload.get("text") or kind),
            source="openshell",
            run_id=handle.run_id,
            data=payload,
            raw=payload,
        )

    async def close(self) -> None:
        await self.source.close()
