"""Framework-neutral contracts shared by the bot and the OpenClaw runtime."""

from agent_voice_bot.core.models import (
    AgentCapabilities,
    AgentEvent,
    AgentRequest,
    AgentResult,
    FollowupResult,
    RunHandle,
)
from agent_voice_bot.core.runtime import AgentRuntime, collect_result

__all__ = [
    "AgentCapabilities",
    "AgentEvent",
    "AgentRequest",
    "AgentResult",
    "AgentRuntime",
    "FollowupResult",
    "RunHandle",
    "collect_result",
]
