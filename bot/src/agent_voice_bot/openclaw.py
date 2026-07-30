"""OpenClaw Gateway runtime, reached through a NemoClaw sandbox.

The bot talks to one backend: an OpenClaw agent whose Gateway websocket is
published by a NemoClaw sandbox. The Gateway is the only surface used here —
`chat.send` to start a run, the `chat` event stream to follow it, `sessions.steer`
to inject a follow-up mid-run, and `chat.abort` to preempt it.

This module owns the vocabulary the agent worker speaks — runs, events, results
— alongside the wire client that produces them. It must not import Pipecat: the
worker adapts these types to bus messages, and keeping that direction one-way is
what lets the Gateway client be tested without media timing.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger

from agent_voice_bot.config import AGENT_LOOP_INSTRUCTION, OpenClawConfig

EventKind = Literal["text_delta", "completed", "cancelled", "failed"]


@dataclass(frozen=True)
class RunHandle:
    """One in-flight agent run, plus the connection needed to steer it."""

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


async def collect_result(events: AsyncIterator[AgentEvent]) -> AgentResult:
    """Fold a run's event stream into the single answer the user hears."""
    parts: list[str] = []
    async for event in events:
        if event.kind == "text_delta" and event.text:
            parts.append(event.text)
        elif event.kind == "completed":
            return AgentResult(event.text or "".join(parts).strip())
        elif event.kind == "cancelled":
            return AgentResult(event.text or "The agent run was cancelled.", "cancelled")
        elif event.kind == "failed":
            return AgentResult(event.text or "The agent run failed.", "error")
    return AgentResult("The agent run ended without a final response.")


class OpenClawRuntime:
    """Runs agent work on an OpenClaw agent behind a NemoClaw sandbox.

    OpenClaw supports the full lifecycle: it streams text, accepts a live steer
    while a run is in flight, and can abort a run. Nothing here fakes a
    capability the Gateway does not actually confirm.
    """

    def __init__(self, config: OpenClawConfig):
        self._config = config

    async def start(self, user_input: str) -> RunHandle:
        conn = _GatewayConnection(self._config)
        await conn.connect()
        run_id = uuid.uuid4().hex
        payload = await conn.request(
            "chat.send",
            {
                "sessionKey": self._config.session_key,
                "message": f"{user_input.rstrip()}\n\n{AGENT_LOOP_INSTRUCTION}",
                "timeoutMs": int(self._config.timeout_secs * 1000),
                "idempotencyKey": run_id,
            },
        )
        return RunHandle(
            run_id=str((payload or {}).get("runId") or run_id),
            metadata={"connection": conn},
        )

    async def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]:
        conn = _connection_from_handle(handle)
        try:
            while True:
                frame = await conn.next_event()
                if frame is None:
                    # The socket dropped before a terminal state arrived. Fail
                    # the run rather than waiting on a queue nothing will fill.
                    yield AgentEvent(
                        "failed",
                        text="The connection to the OpenClaw Gateway closed before the run finished.",
                        run_id=handle.run_id,
                    )
                    return
                if frame.get("event") != "chat":
                    continue
                payload = frame.get("payload")
                if not isinstance(payload, dict):
                    continue
                if payload.get("runId") != handle.run_id:
                    continue
                state = payload.get("state")
                text = _extract_text(payload.get("message"))
                logger.debug("OpenClaw chat frame: {}", payload)
                if state == "delta":
                    yield AgentEvent("text_delta", text=text, run_id=handle.run_id)
                elif state == "final":
                    yield AgentEvent("completed", text=text, run_id=handle.run_id)
                    return
                elif state == "aborted":
                    yield AgentEvent("cancelled", text=text, run_id=handle.run_id)
                    return
                elif state == "error":
                    yield AgentEvent(
                        "failed",
                        text=str(payload.get("errorMessage") or text),
                        run_id=handle.run_id,
                    )
                    return
        finally:
            await conn.close()

    async def send_followup(self, handle: RunHandle, user_input: str) -> FollowupResult:
        conn = _connection_from_handle(handle)
        await conn.request(
            "sessions.steer",
            {
                "key": self._config.session_key,
                "message": user_input,
                "idempotencyKey": uuid.uuid4().hex,
            },
        )
        return FollowupResult(applied=True, status="steered")

    async def stop(self, handle: RunHandle, reason: str | None = None) -> None:
        conn = _connection_from_handle(handle)
        try:
            with suppress(Exception):
                await conn.request(
                    "chat.abort",
                    {"sessionKey": self._config.session_key, "runId": handle.run_id},
                )
        finally:
            await conn.close()


class _GatewayConnection:
    """Minimal OpenClaw Gateway websocket client for chat runs."""

    def __init__(self, config: OpenClawConfig):
        self._config = config
        self._ws: Any | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        # A None on this queue means the reader stopped: the socket closed or
        # errored. Consumers must treat it as the end of the stream.
        self._events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._hello: asyncio.Future = asyncio.get_running_loop().create_future()

    async def connect(self) -> None:
        import websockets

        # Log the resolved gateway/session so it is obvious which sandbox the
        # bot is actually talking to (profiles and .env can disagree).
        logger.info(
            "OpenClaw connecting to gateway {url} (session {session}, token {token})",
            url=self._config.gateway_url,
            session=self._config.session_key,
            token="set" if self._config.token else "unset",
        )
        self._ws = await websockets.connect(
            self._config.gateway_url,
            max_size=25 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._reader())
        await asyncio.wait_for(self._hello, timeout=self._config.timeout_secs)

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._ws is None:
            raise RuntimeError("OpenClaw Gateway is not connected")
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._ws.send(
            json.dumps(
                {"type": "req", "id": request_id, "method": method, "params": params},
                separators=(",", ":"),
            )
        )
        return await asyncio.wait_for(future, timeout=self._config.timeout_secs)

    async def next_event(self) -> dict[str, Any] | None:
        """The next Gateway event, or None once the reader has stopped."""
        return await self._events.get()

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader_task
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _reader(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                frame = json.loads(raw)
                frame_type = frame.get("type")
                if frame_type == "event":
                    if frame.get("event") == "connect.challenge":
                        await self._send_connect()
                    else:
                        await self._events.put(frame)
                    continue
                if frame_type == "res":
                    request_id = frame.get("id")
                    future = self._pending.pop(str(request_id), None)
                    if future is None or future.done():
                        continue
                    if frame.get("ok"):
                        if not self._hello.done() and _is_hello_ok(frame.get("payload")):
                            self._hello.set_result(frame.get("payload"))
                        future.set_result(frame.get("payload"))
                    else:
                        error = frame.get("error") or {}
                        future.set_exception(RuntimeError(error.get("message") or str(error)))
        except Exception as exc:
            if not self._hello.done():
                self._hello.set_exception(exc)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(exc)
            self._pending.clear()
        finally:
            # Whether the socket closed cleanly or blew up, nothing more will
            # arrive. Wake any consumer parked on next_event().
            await self._events.put(None)

    async def _send_connect(self) -> None:
        auth: dict[str, str] = {}
        if self._config.token:
            auth["token"] = self._config.token
        if self._config.password:
            auth["password"] = self._config.password

        params: dict[str, Any] = {
            "minProtocol": 4,
            "maxProtocol": 4,
            "client": {
                "id": "gateway-client",
                "displayName": "agent-voice-bot",
                "version": "0.1.0",
                "platform": sys.platform,
                "mode": "backend",
            },
            "caps": [],
            "role": "operator",
            "scopes": ["operator.admin"],
        }
        if auth:
            params["auth"] = auth
        task = asyncio.create_task(self.request("connect", params))
        task.add_done_callback(self._finish_connect)

    def _finish_connect(self, task: asyncio.Task) -> None:
        if task.cancelled():
            if not self._hello.done():
                self._hello.cancel()
            return
        if self._hello.done():
            with suppress(Exception):
                task.result()
            return
        try:
            self._hello.set_result(task.result())
        except Exception as exc:
            self._hello.set_exception(exc)


def _connection_from_handle(handle: RunHandle) -> _GatewayConnection:
    conn = handle.metadata.get("connection")
    if not isinstance(conn, _GatewayConnection):
        raise RuntimeError("OpenClaw run handle is missing its Gateway connection")
    return conn


def _is_hello_ok(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("type") == "hello-ok"


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "message", "output", "summary"):
            text = value.get(key)
            if isinstance(text, str):
                return text
        content = value.get("content")
        if isinstance(content, list):
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            return "".join(parts)
    return json.dumps(value, ensure_ascii=False)
