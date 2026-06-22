"""Adapters for the agent loop."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from agent_voice_bot.config import AgentLoopConfig


@dataclass(frozen=True)
class AgentLoopRequest:
    """Work item sent from the voice loop to the agent loop."""

    user_request: str
    reason: str
    priority: str = "normal"
    conversation_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentLoopResult:
    """Normalized agent-loop response returned to the voice loop."""

    summary: str
    status: str = "completed"
    raw: Any | None = None


class AgentLoopClient:
    """Dispatches agent-loop work to mock, REST, OpenAI-compatible, or MCP backends."""

    def __init__(self, config: AgentLoopConfig):
        self._config = config

    async def run(self, request: AgentLoopRequest) -> AgentLoopResult:
        mode = self._config.mode
        if mode == "mock":
            return await self._run_mock(request)
        if mode == "rest":
            return await self._run_rest(request)
        if mode == "openai":
            return await self._run_openai_compatible(request)
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

    async def _run_openai_compatible(self, request: AgentLoopRequest) -> AgentLoopResult:
        if not self._config.openai_base_url:
            raise ValueError(
                "AGENT_LOOP_OPENAI_BASE_URL is required when AGENT_LOOP_MODE=openai"
            )

        url = self._config.openai_base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._config.openai_api_key:
            headers["Authorization"] = f"Bearer {self._config.openai_api_key}"

        payload = {
            "model": self._config.openai_model,
            "stream": False,
            "reasoning_effort": self._config.openai_reasoning_effort,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an agent backend. Do the forwarded work or "
                        "return the best next-step summary for another agent."
                    ),
                },
                {"role": "user", "content": json.dumps(_request_payload(request))},
            ],
        }

        async with httpx.AsyncClient(timeout=self._config.timeout_secs) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

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


def _request_payload(request: AgentLoopRequest) -> dict[str, Any]:
    return {
        "user_request": request.user_request,
        "reason": request.reason,
        "priority": request.priority,
        "conversation_summary": request.conversation_summary,
        "metadata": request.metadata,
    }


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
