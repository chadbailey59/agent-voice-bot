"""Maps session events to visual and spoken behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_voice_bot.core.models import AgentEvent


@dataclass(frozen=True)
class Presentation:
    visual_text: str | None = None
    spoken_text: str | None = None
    interrupt: bool = False
    requires_visual_action: bool = False


class EventPresenter(Protocol):
    async def present(self, event: AgentEvent) -> Presentation: ...


class DefaultEventPresenter:
    """Conservative defaults: terminal events speak; operational noise stays visual."""

    async def present(self, event: AgentEvent) -> Presentation:
        if event.kind == "approval_required":
            return Presentation(event.text, "The agent needs your approval on screen.", True, True)
        if event.kind == "policy_denied":
            return Presentation(event.text, "The requested action was blocked by policy.")
        if event.kind == "sandbox_unhealthy":
            return Presentation(event.text, "The agent sandbox is not healthy.")
        if event.kind in {"completed", "failed", "cancelled"}:
            return Presentation(event.text, event.text)
        return Presentation(visual_text=event.text or None)
