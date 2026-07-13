"""Registry-based runtime assembly."""

from __future__ import annotations

from collections.abc import Callable

from agent_voice_bot.agent_loop import AgentLoopClient
from agent_voice_bot.config import AgentLoopConfig
from agent_voice_bot.core.runtime import AgentRuntime


RuntimeBuilder = Callable[[AgentLoopConfig], AgentRuntime]


class RuntimeFactory:
    def __init__(self):
        self._builders: dict[str, RuntimeBuilder] = {}

    def register(self, name: str, builder: RuntimeBuilder) -> None:
        if name in self._builders:
            raise ValueError(f"Runtime {name!r} is already registered")
        self._builders[name] = builder

    def build(self, config: AgentLoopConfig) -> AgentRuntime:
        builder = self._builders.get(config.mode)
        if builder is None:
            raise ValueError(f"Unsupported AGENT_LOOP_MODE: {config.mode!r}")
        return builder(config)


def default_runtime_factory() -> RuntimeFactory:
    factory = RuntimeFactory()
    for mode in ("mock", "rest", "openai", "mcp", "hermes", "nemohermes", "openclaw"):
        factory.register(mode, AgentLoopClient)
    return factory


def build_runtime(config: AgentLoopConfig) -> AgentRuntime:
    return default_runtime_factory().build(config)
