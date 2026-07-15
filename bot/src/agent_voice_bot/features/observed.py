"""Runtime decorator that adds environment events without changing an adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Protocol

from agent_voice_bot.core.models import (
    AgentCapabilities,
    AgentEvent,
    AgentRequest,
    FollowupResult,
    RunHandle,
)
from agent_voice_bot.core.runtime import AgentRuntime


class EventObserver(Protocol):
    @property
    def capabilities(self) -> AgentCapabilities: ...
    def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]: ...
    async def close(self) -> None: ...


class ObservedRuntime:
    def __init__(self, runtime: AgentRuntime, observers: list[EventObserver]):
        self.runtime = runtime
        self.observers = observers

    @property
    def capabilities(self) -> AgentCapabilities:
        values = dict(self.runtime.capabilities.__dict__)
        for observer in self.observers:
            values = {
                key: bool(values[key] or getattr(observer.capabilities, key))
                for key in values
            }
        return AgentCapabilities(**values)

    async def start(self, request: AgentRequest) -> RunHandle:
        return await self.runtime.start(request)

    async def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]:
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def pump(source: AsyncIterator[AgentEvent]) -> None:
            try:
                async for event in source:
                    await queue.put(event)
            finally:
                await queue.put(None)

        sources = [self.runtime.events(handle), *(o.events(handle) for o in self.observers)]
        tasks = [asyncio.create_task(pump(source)) for source in sources]
        finished = 0
        try:
            while finished < len(tasks):
                event = await queue.get()
                if event is None:
                    finished += 1
                    continue
                if event.kind in {"completed", "failed", "cancelled"} and event.source == "agent":
                    # Give observer pumps one scheduling turn to publish control-plane
                    # events correlated with the run before its terminal event.
                    await asyncio.sleep(0)
                    while not queue.empty():
                        pending = queue.get_nowait()
                        if pending is not None:
                            yield pending
                    yield event
                    return
                yield event
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

    async def send_followup(self, handle: RunHandle, user_input: str) -> FollowupResult:
        return await self.runtime.send_followup(handle, user_input)

    async def stop(self, handle: RunHandle, reason: str | None = None) -> None:
        await self.runtime.stop(handle, reason)

    async def close(self) -> None:
        await self.runtime.close()
        for observer in self.observers:
            await observer.close()
