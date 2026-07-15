"""Small dependency-free telemetry hook used by integrations and tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from agent_voice_bot.core.models import AgentEvent


class TelemetrySink(Protocol):
    async def record(self, event: AgentEvent) -> None: ...


class MemoryTelemetrySink:
    def __init__(self):
        self.events: list[AgentEvent] = []

    async def record(self, event: AgentEvent) -> None:
        self.events.append(event)


class JsonlTelemetrySink:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    async def record(self, event: AgentEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": event.kind,
            "source": event.source,
            "run_id": event.run_id,
            "text": event.text,
            "data": event.data,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
