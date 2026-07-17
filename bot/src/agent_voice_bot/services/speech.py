"""Speech-stack providers kept outside the core pipeline."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService

from agent_voice_bot.config import (
    DEFAULT_CARTESIA_VOICE_ID,
    DEFAULT_NVIDIA_ASR_MODEL,
    DEFAULT_NVIDIA_ASR_SERVER,
    DEFAULT_NVIDIA_TTS_MODEL,
    DEFAULT_NVIDIA_TTS_SERVER,
)


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


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _nvidia_riva_stack() -> SpeechStack:
    """Build a fully local speech stack backed by self-hosted NVIDIA NIMs.

    Pipecat's NVIDIA services default to NVIDIA Cloud Functions, so every
    argument here exists to point them at a local Riva deployment instead:
    plain-text gRPC, no credentials, and no NVCF function routing.
    """
    # Imported lazily so the default Deepgram/Cartesia stack keeps working
    # without the optional `nvidia` extra and its riva-client dependency.
    from pipecat.services.nvidia.stt import NvidiaSTTService
    from pipecat.services.nvidia.tts import NvidiaTTSService

    api_key = os.getenv("NVIDIA_API_KEY", "")
    voice = os.getenv("NVIDIA_TTS_VOICE")
    return SpeechStack(
        stt=NvidiaSTTService(
            server=os.getenv("NVIDIA_ASR_SERVER", DEFAULT_NVIDIA_ASR_SERVER),
            api_key=api_key or None,
            use_ssl=_env_flag("NVIDIA_ASR_USE_SSL"),
            model_function_map={
                "model_name": os.getenv("NVIDIA_ASR_MODEL", DEFAULT_NVIDIA_ASR_MODEL)
            },
            settings=NvidiaSTTService.Settings(interim_results=True),
        ),
        tts=NvidiaTTSService(
            server=os.getenv("NVIDIA_TTS_SERVER", DEFAULT_NVIDIA_TTS_SERVER),
            # NvidiaTTSService sends both gRPC metadata headers unconditionally,
            # unlike NvidiaSTTService, which omits them when unset. Passing None
            # here would send a literal "Bearer None" to the local NIM, so send
            # empty strings the server can ignore instead.
            api_key=api_key,
            use_ssl=_env_flag("NVIDIA_TTS_USE_SSL"),
            model_function_map={
                "function_id": os.getenv("NVIDIA_TTS_FUNCTION_ID", ""),
                "model_name": os.getenv("NVIDIA_TTS_MODEL", DEFAULT_NVIDIA_TTS_MODEL),
            },
            # Left unset, Pipecat's own Magpie default voice applies, which
            # suits the default model. A FastPitch NIM serves different voices
            # and needs an explicit name.
            settings=NvidiaTTSService.Settings(voice=voice) if voice else None,
        ),
        vad=SileroVADAnalyzer(),
    )


def default_speech_factory() -> SpeechStackFactory:
    factory = SpeechStackFactory()
    factory.register("deepgram-cartesia", _commercial_stack)
    factory.register("nvidia-riva", _nvidia_riva_stack)
    return factory
