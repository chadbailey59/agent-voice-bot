"""Framework-neutral session models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EventKind = Literal[
    "run_started",
    "progress",
    "text_delta",
    "tool_started",
    "tool_finished",
    "approval_required",
    "approval_resolved",
    "policy_denied",
    "sandbox_unhealthy",
    "completed",
    "cancelled",
    "failed",
]


@dataclass(frozen=True)
class AgentCapabilities:
    streaming: bool = False
    steering: bool = False
    cancellation: bool = False
    session_continuation: bool = False
    approvals: bool = False
    tool_events: bool = False

    def with_features(self, **features: bool) -> "AgentCapabilities":
        values = self.__dict__ | features
        return AgentCapabilities(**values)


@dataclass(frozen=True)
class AgentRequest:
    user_request: str
    reason: str
    priority: str = "normal"
    conversation_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    summary: str
    status: str = "completed"
    raw: Any | None = None


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    session_id: str | None = None
    backend: str = "legacy"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentEvent:
    kind: EventKind
    text: str = ""
    source: str = "agent"
    run_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    raw: Any | None = None


@dataclass(frozen=True)
class FollowupResult:
    applied: bool
    status: str
    raw: Any | None = None
