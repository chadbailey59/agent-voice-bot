"""Ordered feature composition for optional integrations."""

from __future__ import annotations

from collections.abc import Callable

from agent_voice_bot.core.runtime import AgentRuntime

FeatureBuilder = Callable[[AgentRuntime], AgentRuntime]


class FeatureRegistry:
    def __init__(self):
        self._builders: dict[str, FeatureBuilder] = {}

    def register(self, name: str, builder: FeatureBuilder) -> None:
        if name in self._builders:
            raise ValueError(f"Feature {name!r} is already registered")
        self._builders[name] = builder

    def apply(self, runtime: AgentRuntime, names: tuple[str, ...]) -> AgentRuntime:
        result = runtime
        for name in names:
            try:
                result = self._builders[name](result)
            except KeyError as exc:
                raise ValueError(f"Unsupported AGENT_VOICE_FEATURE: {name!r}") from exc
        return result
