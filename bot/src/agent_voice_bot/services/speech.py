"""Speech-stack providers kept outside the core pipeline."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService

from agent_voice_bot.config import DEFAULT_CARTESIA_VOICE_ID


@dataclass(frozen=True)
class SpeechStack:
    stt: Any
    tts: Any
    vad: Any


SpeechBuilder = Callable[[], SpeechStack]


class SpeechStackFactory:
    def __init__(self):
        self._builders: dict[str, SpeechBuilder] = {}

    def register(self, name: str, builder: SpeechBuilder) -> None:
        if name in self._builders:
            raise ValueError(f"Speech provider {name!r} is already registered")
        self._builders[name] = builder

    def build(self, name: str) -> SpeechStack:
        try:
            return self._builders[name]()
        except KeyError as exc:
            raise ValueError(f"Unsupported SPEECH_PROVIDER: {name!r}") from exc


def _commercial_stack() -> SpeechStack:
    return SpeechStack(
        stt=DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"]),
        tts=CartesiaTTSService(
            api_key=os.environ["CARTESIA_API_KEY"],
            settings=CartesiaTTSService.Settings(
                voice=os.getenv("CARTESIA_VOICE_ID", DEFAULT_CARTESIA_VOICE_ID)
            ),
        ),
        vad=SileroVADAnalyzer(),
    )


def default_speech_factory() -> SpeechStackFactory:
    factory = SpeechStackFactory()
    factory.register("deepgram-cartesia", _commercial_stack)
    return factory
