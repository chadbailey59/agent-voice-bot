"""Adapters for the agent loop."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from contextlib import suppress
from typing import Any, AsyncIterator

import httpx
from loguru import logger

from agent_voice_bot.config import AgentLoopConfig, PLAIN_SPOKEN_OUTPUT_INSTRUCTION
from agent_voice_bot.core.models import (
    AgentCapabilities,
    AgentEvent as AgentLoopEvent,
    AgentRequest as AgentLoopRequest,
    AgentResult as AgentLoopResult,
    FollowupResult as AgentLoopFollowupResult,
    RunHandle as AgentLoopRunHandle,
)


class AgentLoopClient:
    """Dispatches agent-loop work to local or remote backends.

    The worker uses the evented lifecycle: start, optional follow-up, wait, and
    stop. The old run() API remains as a compatibility wrapper for simple tests
    and blocking backends.
    """

    def __init__(self, config: AgentLoopConfig):
        self._config = config

    @property
    def capabilities(self) -> AgentCapabilities:
        if self._config.mode == "openclaw":
            return AgentCapabilities(True, True, True, True, tool_events=True)
        if self._config.mode == "hermes":
            return AgentCapabilities(True, False, True, True)
        if self._config.mode == "nemohermes":
            return AgentCapabilities(False, False, False, True)
        return AgentCapabilities(cancellation=True)

    async def close(self) -> None:
        """Compatibility hook for the framework-neutral runtime contract."""

    async def run(self, request: AgentLoopRequest) -> AgentLoopResult:
        handle = await self.start(request)
        return await self.wait(handle)

    async def start(self, request: AgentLoopRequest) -> AgentLoopRunHandle:
        mode = self._config.mode
        if mode == "hermes":
            return await self._start_hermes(request)
        if mode == "openclaw":
            return await self._start_openclaw(request)
        if mode in {"mock", "rest", "openai", "mcp", "nemohermes"}:
            return self._start_legacy(request)
        raise ValueError(f"Unsupported AGENT_LOOP_MODE: {mode!r}")

    async def wait(self, handle: AgentLoopRunHandle) -> AgentLoopResult:
        if handle.backend == "legacy":
            task = handle.metadata.get("task")
            if not isinstance(task, asyncio.Task):
                raise RuntimeError("Legacy agent run handle is missing its task")
            return await task

        parts: list[str] = []
        async for event in self.events(handle):
            if event.kind == "text_delta" and event.text:
                parts.append(event.text)
            elif event.kind == "completed":
                summary = event.text or "".join(parts).strip()
                return AgentLoopResult(summary=summary, raw=event.raw)
            elif event.kind == "cancelled":
                return AgentLoopResult(
                    summary="The agent run was cancelled.",
                    status="cancelled",
                    raw=event.raw,
                )
            elif event.kind == "failed":
                return AgentLoopResult(
                    summary=event.text or "The agent run failed.",
                    status="error",
                    raw=event.raw,
                )

        return AgentLoopResult(summary="The agent run ended without a final response.")

    async def events(self, handle: AgentLoopRunHandle) -> AsyncIterator[AgentLoopEvent]:
        if handle.backend == "hermes":
            async for event in self._events_hermes(handle):
                yield event
            return
        if handle.backend == "openclaw":
            async for event in self._events_openclaw(handle):
                yield event
            return
        if handle.backend == "legacy":
            result = await self.wait(handle)
            yield AgentLoopEvent("completed", text=result.summary, raw=result.raw)
            return
        raise ValueError(f"Unsupported agent run backend: {handle.backend!r}")

    async def send_followup(
        self,
        handle: AgentLoopRunHandle,
        user_input: str,
    ) -> AgentLoopFollowupResult:
        if handle.backend == "openclaw":
            return await self._followup_openclaw(handle, user_input)
        if handle.backend == "hermes":
            return AgentLoopFollowupResult(
                applied=False,
                status="Hermes HTTP runs do not expose live steering; stop and resend if needed.",
            )
        return AgentLoopFollowupResult(
            applied=False,
            status=f"{handle.backend} backend does not support live follow-up.",
        )

    async def stop(self, handle: AgentLoopRunHandle, reason: str | None = None) -> None:
        if handle.backend == "hermes":
            await self._stop_hermes(handle, reason)
            return
        if handle.backend == "openclaw":
            await self._stop_openclaw(handle, reason)
            return
        if handle.backend == "legacy":
            task = handle.metadata.get("task")
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def _start_legacy(self, request: AgentLoopRequest) -> AgentLoopRunHandle:
        task = asyncio.create_task(self._run_legacy(request))
        return AgentLoopRunHandle(
            run_id=f"local_{uuid.uuid4().hex}",
            backend="legacy",
            metadata={"task": task},
        )

    async def _run_legacy(self, request: AgentLoopRequest) -> AgentLoopResult:
        mode = self._config.mode
        if mode == "mock":
            return await self._run_mock(request)
        if mode == "rest":
            return await self._run_rest(request)
        if mode == "openai":
            return await self._run_openai_compatible(
                request,
                base_url=self._config.openai_base_url,
                api_key=self._config.openai_api_key,
                model=self._config.openai_model,
                reasoning_effort=self._config.openai_reasoning_effort,
            )
        if mode == "nemohermes":
            return await self._run_openai_compatible(
                request,
                base_url=self._config.nemohermes_base_url,
                api_key=self._config.nemohermes_api_key,
                model=self._config.nemohermes_model,
                reasoning_effort=None,
                missing_url_env="AGENT_LOOP_NEMOHERMES_BASE_URL",
                session_log_label="NemoHermes",
            )
        if mode == "mcp":
            return await self._run_mcp(request)
        raise ValueError(f"Unsupported AGENT_LOOP_MODE: {mode!r}")

    async def _run_mock(self, request: AgentLoopRequest) -> AgentLoopResult:
        # Simulate a slow agent backend. The delay lets evals verify that the
        # voice loop stays responsive while this runs, and the marker (a stable
        # "confirmation code") lets the return-path eval assert that the result
        # actually made it back and was relayed to the user.
        await asyncio.sleep(self._config.mock_delay_secs)
        return AgentLoopResult(
            summary=(
                f"Background task completed the request '{request.user_request}'. "
                f"Confirmation code: {self._config.mock_result}."
            ),
            raw={"mode": "mock", "reason": request.reason},
        )

    async def _run_rest(self, request: AgentLoopRequest) -> AgentLoopResult:
        if not self._config.rest_url:
            raise ValueError("AGENT_LOOP_REST_URL is required when AGENT_LOOP_MODE=rest")

        async with httpx.AsyncClient(timeout=self._config.timeout_secs) as client:
            response = await client.post(self._config.rest_url, json=_request_payload(request))
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        payload: Any = response.json() if "application/json" in content_type else response.text
        return _result_from_payload(payload)

    async def _run_openai_compatible(
        self,
        request: AgentLoopRequest,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        reasoning_effort: str | None,
        missing_url_env: str = "AGENT_LOOP_OPENAI_BASE_URL",
        session_log_label: str | None = None,
    ) -> AgentLoopResult:
        if not base_url:
            raise ValueError(f"{missing_url_env} is required for this OpenAI-compatible mode")

        url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an agent backend. Do the forwarded work or "
                        "return the best next-step summary for another agent. "
                        f"{PLAIN_SPOKEN_OUTPUT_INSTRUCTION}"
                    ),
                },
                {"role": "user", "content": json.dumps(_request_payload(request))},
            ],
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        async with httpx.AsyncClient(timeout=self._config.timeout_secs) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

        if session_log_label:
            session_id = _response_header(response, "X-Hermes-Session-Id")
            if session_id:
                logger.info(
                    "{} session id: {}. Tail with: nemohermes nh exec -- hermes logs --session {} -f",
                    session_log_label,
                    session_id,
                    session_id,
                )

        payload = response.json()
        text = payload["choices"][0]["message"].get("content") or ""
        return AgentLoopResult(summary=text.strip(), raw=payload)

    async def _run_mcp(self, request: AgentLoopRequest) -> AgentLoopResult:
        try:
            from mcp import StdioServerParameters
            from mcp.client.session_group import SseServerParameters, StreamableHttpParameters
            from pipecat.services.mcp_service import MCPClient
        except ImportError as exc:
            raise RuntimeError(
                "MCP mode requires the mcp extra, for example: uv add 'pipecat-ai[mcp]'"
            ) from exc

        transport = self._config.mcp_transport
        if transport == "stdio":
            if not self._config.mcp_command:
                raise ValueError("AGENT_LOOP_MCP_COMMAND is required for MCP stdio mode")
            server_params = StdioServerParameters(
                command=self._config.mcp_command,
                args=self._config.mcp_args,
            )
        elif transport == "sse":
            if not self._config.mcp_url:
                raise ValueError("AGENT_LOOP_MCP_URL is required for MCP SSE mode")
            server_params = SseServerParameters(url=self._config.mcp_url)
        elif transport in {"http", "streamable-http"}:
            if not self._config.mcp_url:
                raise ValueError("AGENT_LOOP_MCP_URL is required for MCP HTTP mode")
            server_params = StreamableHttpParameters(url=self._config.mcp_url)
        else:
            raise ValueError(f"Unsupported AGENT_LOOP_MCP_TRANSPORT: {transport!r}")

        async with MCPClient(server_params=server_params) as mcp:
            session = mcp._ensure_connected()
            result = await session.call_tool(
                self._config.mcp_tool,
                arguments=_request_payload(request),
            )

        text_parts = [
            item.text
            for item in getattr(result, "content", []) or []
            if getattr(item, "text", None)
        ]
        text = "\n".join(text_parts).strip()
        return AgentLoopResult(summary=text or "The MCP tool completed without text output.", raw=result)

    async def _start_hermes(self, request: AgentLoopRequest) -> AgentLoopRunHandle:
        if not self._config.hermes_base_url:
            raise ValueError("AGENT_LOOP_HERMES_BASE_URL is required when AGENT_LOOP_MODE=hermes")

        headers = _hermes_headers(self._config)
        if self._config.hermes_session_key:
            headers["X-Hermes-Session-Key"] = self._config.hermes_session_key

        body: dict[str, Any] = {
            "model": self._config.hermes_model,
            "input": request.user_request,
            "instructions": _with_plain_spoken_instruction(request.reason),
        }
        if request.conversation_summary:
            body["conversation_history"] = [
                {
                    "role": "system",
                    "content": f"Conversation summary: {request.conversation_summary}",
                }
            ]

        async with httpx.AsyncClient(timeout=self._config.timeout_secs) as client:
            response = await client.post(
                _v1_url(self._config.hermes_base_url, "/runs"),
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            payload = response.json()

        run_id = str(payload.get("run_id") or "")
        if not run_id:
            raise RuntimeError(f"Hermes did not return a run_id: {payload!r}")
        return AgentLoopRunHandle(
            run_id=run_id,
            session_id=self._config.hermes_session_key or None,
            backend="hermes",
            metadata={"start": payload},
        )

    async def _events_hermes(self, handle: AgentLoopRunHandle) -> AsyncIterator[AgentLoopEvent]:
        assert self._config.hermes_base_url is not None
        url = _v1_url(self._config.hermes_base_url, f"/runs/{handle.run_id}/events")
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url, headers=_hermes_headers(self._config)) as response:
                response.raise_for_status()
                async for payload in _iter_sse_json(response):
                    event_name = str(payload.get("event", ""))
                    if event_name == "message.delta":
                        yield AgentLoopEvent("text_delta", text=str(payload.get("delta", "")), run_id=handle.run_id, raw=payload)
                    elif event_name == "run.completed":
                        yield AgentLoopEvent("completed", text=str(payload.get("output", "")), run_id=handle.run_id, raw=payload)
                        return
                    elif event_name == "run.failed":
                        yield AgentLoopEvent("failed", text=str(payload.get("error", "")), run_id=handle.run_id, raw=payload)
                        return
                    elif event_name in {"run.cancelled", "run.stopped"}:
                        yield AgentLoopEvent("cancelled", run_id=handle.run_id, raw=payload)
                        return
                    elif event_name:
                        yield AgentLoopEvent("progress", text=event_name, run_id=handle.run_id, raw=payload)

    async def _stop_hermes(self, handle: AgentLoopRunHandle, reason: str | None = None) -> None:
        assert self._config.hermes_base_url is not None
        url = _v1_url(self._config.hermes_base_url, f"/runs/{handle.run_id}/stop")
        body = {"reason": reason} if reason else None
        async with httpx.AsyncClient(timeout=self._config.timeout_secs) as client:
            response = await client.post(url, headers=_hermes_headers(self._config), json=body)
            if response.status_code != 404:
                response.raise_for_status()

    async def _start_openclaw(self, request: AgentLoopRequest) -> AgentLoopRunHandle:
        conn = _OpenClawGatewayConnection(self._config)
        await conn.connect()
        run_id = uuid.uuid4().hex
        payload = await conn.request(
            "chat.send",
            {
                "sessionKey": self._config.openclaw_session_key,
                "message": _with_plain_spoken_instruction(request.user_request),
                "timeoutMs": int(self._config.timeout_secs * 1000),
                "idempotencyKey": run_id,
            },
        )
        actual_run_id = str((payload or {}).get("runId") or run_id)
        return AgentLoopRunHandle(
            run_id=actual_run_id,
            session_id=self._config.openclaw_session_key,
            backend="openclaw",
            metadata={"connection": conn, "start": payload},
        )

    async def _events_openclaw(self, handle: AgentLoopRunHandle) -> AsyncIterator[AgentLoopEvent]:
        conn = _openclaw_connection_from_handle(handle)
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
                    yield AgentLoopEvent("text_delta", text=text, run_id=handle.run_id, raw=payload)
                elif state == "final":
                    yield AgentLoopEvent("completed", text=text, run_id=handle.run_id, raw=payload)
                    return
                elif state == "aborted":
                    yield AgentLoopEvent("cancelled", text=text, run_id=handle.run_id, raw=payload)
                    return
                elif state == "error":
                    yield AgentLoopEvent(
                        "failed",
                        text=str(payload.get("errorMessage") or text),
                        run_id=handle.run_id,
                        raw=payload,
                    )
                    return
        finally:
            await conn.close()

    async def _followup_openclaw(
        self,
        handle: AgentLoopRunHandle,
        user_input: str,
    ) -> AgentLoopFollowupResult:
        conn = _openclaw_connection_from_handle(handle)
        payload = await conn.request(
            "sessions.steer",
            {
                "key": self._config.openclaw_session_key,
                "message": user_input,
                "idempotencyKey": uuid.uuid4().hex,
            },
        )
        return AgentLoopFollowupResult(applied=True, status="steered", raw=payload)

    async def _stop_openclaw(self, handle: AgentLoopRunHandle, reason: str | None = None) -> None:
        conn = _openclaw_connection_from_handle(handle)
        try:
            with suppress(Exception):
                await conn.request(
                    "chat.abort",
                    {
                        "sessionKey": self._config.openclaw_session_key,
                        "runId": handle.run_id,
                    },
                )
        finally:
            await conn.close()


class _OpenClawGatewayConnection:
    """Minimal OpenClaw Gateway WS client for chat runs."""

    def __init__(self, config: AgentLoopConfig):
        self._config = config
        self._ws: Any | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._hello: asyncio.Future = asyncio.get_running_loop().create_future()

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "OpenClaw mode requires the websockets package. Install project dependencies."
            ) from exc

        # Log the resolved gateway/session so it is obvious which sandbox the
        # bot is actually talking to (env profiles and .env can disagree).
        logger.info(
            "OpenClaw connecting to gateway {url} (session {session}, token {token})",
            url=self._config.openclaw_gateway_url,
            session=self._config.openclaw_session_key,
            token="set" if self._config.openclaw_token else "unset",
        )
        self._ws = await websockets.connect(
            self._config.openclaw_gateway_url,
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
                {
                    "type": "req",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
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
        if self._config.openclaw_token:
            auth["token"] = self._config.openclaw_token
        if self._config.openclaw_password:
            auth["password"] = self._config.openclaw_password

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


def _request_payload(request: AgentLoopRequest) -> dict[str, Any]:
    return {
        "user_request": request.user_request,
        "reason": _with_plain_spoken_instruction(request.reason),
        "priority": request.priority,
        "conversation_summary": request.conversation_summary,
        "metadata": request.metadata,
    }


def _with_plain_spoken_instruction(text: str) -> str:
    if PLAIN_SPOKEN_OUTPUT_INSTRUCTION in text:
        return text
    return f"{text.rstrip()} {PLAIN_SPOKEN_OUTPUT_INSTRUCTION}"


def _result_from_payload(payload: Any) -> AgentLoopResult:
    if isinstance(payload, str):
        return AgentLoopResult(summary=payload)
    if not isinstance(payload, dict):
        return AgentLoopResult(summary=str(payload), raw=payload)

    summary = (
        payload.get("summary")
        or payload.get("answer")
        or payload.get("result")
        or payload.get("message")
        or json.dumps(payload, ensure_ascii=False)
    )
    return AgentLoopResult(
        summary=str(summary),
        status=str(payload.get("status", "completed")),
        raw=payload,
    )


def _hermes_headers(config: AgentLoopConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.hermes_api_key:
        headers["Authorization"] = f"Bearer {config.hermes_api_key}"
    return headers


def _v1_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base + path
    return base + "/v1" + path


def _response_header(response: httpx.Response, name: str) -> str:
    value = response.headers.get(name) or response.headers.get(name.lower())
    return str(value or "").strip()


async def _iter_sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                data_lines.clear()
                if data == "[DONE]":
                    return
                yield json.loads(data)
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        data = "\n".join(data_lines)
        if data != "[DONE]":
            yield json.loads(data)


def _openclaw_connection_from_handle(handle: AgentLoopRunHandle) -> _OpenClawGatewayConnection:
    conn = handle.metadata.get("connection")
    if not isinstance(conn, _OpenClawGatewayConnection):
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
