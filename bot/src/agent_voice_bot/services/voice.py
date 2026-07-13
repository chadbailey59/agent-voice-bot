"""Voice-coordinator LLM providers."""

from __future__ import annotations

import os
from typing import Any, Callable

from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService

from agent_voice_bot.config import (
    VOICE_LOOP_MODEL,
    VOICE_LOOP_REASONING_EFFORT,
    VOICE_LOOP_SYSTEM_PROMPT,
)


VoiceBuilder = Callable[[], Any]


class VoiceServiceFactory:
    def __init__(self):
        self._builders: dict[str, VoiceBuilder] = {}

    def register(self, name: str, builder: VoiceBuilder) -> None:
        if name in self._builders:
            raise ValueError(f"Voice provider {name!r} is already registered")
        self._builders[name] = builder

    def build(self, name: str) -> Any:
        try:
            return self._builders[name]()
        except KeyError as exc:
            raise ValueError(f"Unsupported VOICE_PROVIDER: {name!r}") from exc


def _openai_voice() -> OpenAIResponsesLLMService:
    return OpenAIResponsesLLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAIResponsesLLMService.Settings(
            model=VOICE_LOOP_MODEL,
            system_instruction=VOICE_LOOP_SYSTEM_PROMPT,
            extra={"reasoning": {"effort": VOICE_LOOP_REASONING_EFFORT}},
        ),
    )


def default_voice_factory() -> VoiceServiceFactory:
    factory = VoiceServiceFactory()
    factory.register("openai", _openai_voice)
    return factory
