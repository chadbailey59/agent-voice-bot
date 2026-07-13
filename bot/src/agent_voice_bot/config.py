"""Configuration for the reference bot."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


VOICE_LOOP_MODEL = os.getenv("VOICE_LOOP_MODEL", "gpt-5.4-mini")
VOICE_LOOP_REASONING_EFFORT = os.getenv("VOICE_LOOP_REASONING_EFFORT", "none")
VOICE_LOOP_WORKER = "voice-loop"
MAIN_WORKER = "main"
AGENT_LOOP_WORKER = "agent-loop"

DEFAULT_CARTESIA_VOICE_ID = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"

PLAIN_SPOKEN_OUTPUT_INSTRUCTION = (
    "Use plain spoken text only. Do not use markdown, bullets, numbered lists, "
    "code fences, backticks, asterisks, emojis, links, citations, or special "
    "formatting characters."
)


VOICE_LOOP_SYSTEM_PROMPT = """\
You are the voice loop for Agent Voice Bot.

The user is speaking, so keep responses concise and natural. Answer simple,
low-risk questions directly when you can do so immediately. For any task that
requires research, tool use, long planning, code changes, file or web access,
multi-step execution, integration with an external agent, or waiting on slow
work, call send_to_agent_loop instead of trying to solve it yourself.

Use send_to_agent_loop both to start new agent work and to forward a follow-up,
correction, or refinement while agent work is already running — just pass along
what the user said and let the agent loop sort out the rest. While agent work
runs, keep answering simple questions directly. If the user wants to abort the
running work, call stop_agent_loop.

When you forward work, say only a very short acknowledgement of one to four
words, such as "One sec.", "Hang on.", or "On it." Do not add filler, status
details, or calls to action to delegation acknowledgements.

If an agent-loop result arrives later in a developer message, summarize it
conversationally. Do not expose internal worker names unless the user asks
about the architecture.

Use plain spoken text only. Do not use markdown, bullets, numbered lists, code
fences, backticks, asterisks, emojis, links, citations, or special formatting
characters.
"""


@dataclass(frozen=True)
class AgentLoopConfig:
    """Backend settings for the agent loop adapter."""

    mode: str = "mock"
    timeout_secs: float = 60.0
    mock_delay_secs: float = 0.2
    mock_result: str = "ZEBRA-4417"
    rest_url: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"
    openai_reasoning_effort: str = "high"
    mcp_transport: str = "stdio"
    mcp_command: str | None = None
    mcp_args: list[str] = field(default_factory=list)
    mcp_url: str | None = None
    mcp_tool: str = "run_agent"
    hermes_base_url: str | None = None
    hermes_api_key: str | None = None
    hermes_model: str = "hermes-agent"
    hermes_session_key: str | None = None
    nemohermes_base_url: str = "http://127.0.0.1:8642/v1"
    nemohermes_api_key: str | None = None
    nemohermes_model: str = "hermes-agent"
    openclaw_gateway_url: str = "ws://127.0.0.1:18789"
    openclaw_token: str | None = None
    openclaw_password: str | None = None
    openclaw_session_key: str = "agent:main:main"

    @classmethod
    def from_env(cls) -> "AgentLoopConfig":
        mcp_args_raw = os.getenv("AGENT_LOOP_MCP_ARGS", "[]")
        try:
            mcp_args: list[str] = json.loads(mcp_args_raw)
        except json.JSONDecodeError:
            mcp_args = [part for part in mcp_args_raw.split(" ") if part]

        return cls(
            mode=(
                os.getenv("AGENT_LOOP_MODE_OVERRIDE")
                or os.getenv("AGENT_LOOP_MODE", "mock")
            ).lower(),
            timeout_secs=float(os.getenv("AGENT_LOOP_TIMEOUT_SECS", "60")),
            mock_delay_secs=float(os.getenv("AGENT_LOOP_MOCK_DELAY_SECS", "0.2")),
            mock_result=os.getenv("AGENT_LOOP_MOCK_RESULT", "ZEBRA-4417"),
            rest_url=os.getenv("AGENT_LOOP_REST_URL"),
            openai_base_url=os.getenv("AGENT_LOOP_OPENAI_BASE_URL"),
            openai_api_key=os.getenv("AGENT_LOOP_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("AGENT_LOOP_OPENAI_MODEL", "gpt-4.1"),
            openai_reasoning_effort=os.getenv("AGENT_LOOP_REASONING_EFFORT", "high"),
            mcp_transport=os.getenv("AGENT_LOOP_MCP_TRANSPORT", "stdio").lower(),
            mcp_command=os.getenv("AGENT_LOOP_MCP_COMMAND"),
            mcp_args=mcp_args,
            mcp_url=os.getenv("AGENT_LOOP_MCP_URL"),
            mcp_tool=os.getenv("AGENT_LOOP_MCP_TOOL", "run_agent"),
            hermes_base_url=os.getenv("AGENT_LOOP_HERMES_BASE_URL"),
            hermes_api_key=os.getenv("AGENT_LOOP_HERMES_API_KEY")
            or os.getenv("API_SERVER_KEY"),
            hermes_model=os.getenv("AGENT_LOOP_HERMES_MODEL", "hermes-agent"),
            hermes_session_key=os.getenv("AGENT_LOOP_HERMES_SESSION_KEY"),
            nemohermes_base_url=os.getenv(
                "AGENT_LOOP_NEMOHERMES_BASE_URL",
                "http://127.0.0.1:8642/v1",
            ),
            nemohermes_api_key=os.getenv("AGENT_LOOP_NEMOHERMES_API_KEY"),
            nemohermes_model=os.getenv("AGENT_LOOP_NEMOHERMES_MODEL", "hermes-agent"),
            openclaw_gateway_url=os.getenv(
                "AGENT_LOOP_OPENCLAW_GATEWAY_URL",
                "ws://127.0.0.1:18789",
            ),
            openclaw_token=os.getenv("AGENT_LOOP_OPENCLAW_TOKEN"),
            openclaw_password=os.getenv("AGENT_LOOP_OPENCLAW_PASSWORD"),
            openclaw_session_key=os.getenv(
                "AGENT_LOOP_OPENCLAW_SESSION_KEY",
                "agent:main:main",
            ),
        )


@dataclass(frozen=True)
class AppConfig:
    speech_provider: str = "deepgram-cartesia"
    voice_provider: str = "openai"
    features: tuple[str, ...] = ()
    agent: AgentLoopConfig = field(default_factory=AgentLoopConfig)

    @classmethod
    def from_env(cls) -> "AppConfig":
        features = tuple(
            item.strip().lower()
            for item in os.getenv("AGENT_VOICE_FEATURES", "").split(",")
            if item.strip()
        )
        return cls(
            speech_provider=os.getenv("SPEECH_PROVIDER", "deepgram-cartesia").lower(),
            voice_provider=os.getenv("VOICE_PROVIDER", "openai").lower(),
            features=features,
            agent=AgentLoopConfig.from_env(),
        )


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
