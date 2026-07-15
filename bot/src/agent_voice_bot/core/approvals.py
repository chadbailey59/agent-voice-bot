"""Optional human-approval boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    run_id: str
    prompt: str
    risk: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


class ApprovalController(Protocol):
    def pending(self, run_id: str) -> AsyncIterator[ApprovalRequest]: ...
    async def approve(self, approval_id: str) -> None: ...
    async def reject(self, approval_id: str, reason: str | None = None) -> None: ...


class NullApprovalController:
    async def pending(self, run_id: str) -> AsyncIterator[ApprovalRequest]:
        if False:
            yield ApprovalRequest("", run_id, "")

    async def approve(self, approval_id: str) -> None:
        raise RuntimeError("Approval support is not configured")

    async def reject(self, approval_id: str, reason: str | None = None) -> None:
        raise RuntimeError("Approval support is not configured")
