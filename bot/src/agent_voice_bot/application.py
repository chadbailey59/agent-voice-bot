"""Composition root for a configured agent runtime."""

from __future__ import annotations

import os

from agent_voice_bot.config import AppConfig
from agent_voice_bot.core.runtime import AgentRuntime
from agent_voice_bot.features import FeatureRegistry
from agent_voice_bot.features.telemetry import JsonlTelemetrySink
from agent_voice_bot.nemo import JsonlEventSource, register_nemo_features
from agent_voice_bot.runtimes import build_runtime


def build_application_runtime(
    config: AppConfig,
    *,
    features: FeatureRegistry | None = None,
) -> AgentRuntime:
    runtime = build_runtime(config.agent)
    if not config.features:
        return runtime
    if features is None:
        raise ValueError(
            "AGENT_VOICE_FEATURES were configured, but no feature registry was installed"
        )
    return features.apply(runtime, config.features)


def build_env_feature_registry() -> FeatureRegistry | None:
    events_path = os.getenv("OPENSHELL_EVENTS_FILE")
    telemetry_path = os.getenv("AGENT_VOICE_TELEMETRY_FILE")
    if not events_path or not telemetry_path:
        return None
    registry = FeatureRegistry()
    register_nemo_features(
        registry,
        source=JsonlEventSource(events_path),
        telemetry=JsonlTelemetrySink(telemetry_path),
    )
    return registry
