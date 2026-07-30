"""OpenClaw Gateway runtime, reached through a NemoClaw sandbox.

The bot talks to one backend: an OpenClaw agent whose Gateway websocket is
published by a NemoClaw sandbox. The Gateway is the only surface used here —
`chat.send` to start a run, the `chat` event stream to follow it, `sessions.steer`
to inject a follow-up mid-run, and `chat.abort` to preempt it.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from loguru import logger

from agent_voice_bot.config import PLAIN_SPOKEN_OUTPUT_INSTRUCTION, OpenClawConfig
from agent_voice_bot.core.models import (
    AgentCapabilities,
    AgentEvent,
    AgentRequest,
    FollowupResult,
    RunHandle,
)


class OpenClawRuntime:
    """Runs agent work on an OpenClaw agent behind a NemoClaw sandbox.

    OpenClaw is the one backend that supports the full lifecycle: it streams
    text, accepts a live steer while a run is in flight, and can abort a run.
    Nothing here fakes a capability the Gateway does not actually confirm.
    """

    capabilities = AgentCapabilities(
        streaming=True,
        steering=True,
        cancellation=True,
        session_continuation=True,
        tool_events=True,
    )

    def __init__(self, config: OpenClawConfig):
        self._config = config

    async def start(self, request: AgentRequest) -> RunHandle:
        conn = _GatewayConnection(self._config)
        await conn.connect()
        run_id = uuid.uuid4().hex
        payload = await conn.request(
            "chat.send",
            {
                "sessionKey": self._config.session_key,
                "message": _with_plain_spoken_instruction(request.user_request),
                "timeoutMs": int(self._config.timeout_secs * 1000),
                "idempotencyKey": run_id,
            },
        )
        return RunHandle(
            run_id=str((payload or {}).get("runId") or run_id),
            session_id=self._config.session_key,
            backend="openclaw",
            metadata={"connection": conn, "start": payload},
        )

    async def events(self, handle: RunHandle) -> AsyncIterator[AgentEvent]:
        conn = _connection_from_handle(handle)
        try:
            while True:
                frame = await conn.next_event()
                if frame.get("event") != "chat":
                    continue
                payload = frame.get("payload")
                if not isinstance(payload, dict):
                    continue
                if payload.get("runId") != handle.run_id:
                    continue
                state = payload.get("state")
                text = _extract_text(payload.get("message"))
                if state == "delta":
                    yield AgentEvent("text_delta", text=text, run_id=handle.run_id, raw=payload)
                elif state == "final":
                    yield AgentEvent("completed", text=text, run_id=handle.run_id, raw=payload)
                    return
                elif state == "aborted":
                    yield AgentEvent("cancelled", text=text, run_id=handle.run_id, raw=payload)
                    return
                elif state == "error":
                    yield AgentEvent(
                        "failed",
                        text=str(payload.get("errorMessage") or text),
                        run_id=handle.run_id,
                        raw=payload,
                    )
                    return
        finally:
            await conn.close()

    async def send_followup(self, handle: RunHandle, user_input: str) -> FollowupResult:
        conn = _connection_from_handle(handle)
        payload = await conn.request(
            "sessions.steer",
            {
                "key": self._config.session_key,
                "message": user_input,
                "idempotencyKey": uuid.uuid4().hex,
            },
        )
        return FollowupResult(applied=True, status="steered", raw=payload)

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

    async def close(self) -> None:
        """No process-wide state: each run owns its own Gateway connection."""


class _GatewayConnection:
    """Minimal OpenClaw Gateway websocket client for chat runs."""

    def __init__(self, config: OpenClawConfig):
        self._config = config
        self._ws: Any | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
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

    async def next_event(self) -> dict[str, Any]:
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


def _with_plain_spoken_instruction(text: str) -> str:
    if PLAIN_SPOKEN_OUTPUT_INSTRUCTION in text:
        return text
    return f"{text.rstrip()} {PLAIN_SPOKEN_OUTPUT_INSTRUCTION}"


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
