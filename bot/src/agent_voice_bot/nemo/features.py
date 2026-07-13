"""Registers Nemo integrations without introducing core-to-Nemo imports."""

from __future__ import annotations

from agent_voice_bot.features import FeatureRegistry, ObservedRuntime, TelemetryRuntime
from agent_voice_bot.features.telemetry import TelemetrySink
from agent_voice_bot.nemo.observer import OpenShellEventSource, OpenShellObserver


def register_nemo_features(
    registry: FeatureRegistry,
    *,
    source: OpenShellEventSource,
    telemetry: TelemetrySink,
) -> None:
    registry.register(
        "openshell-events",
        lambda runtime: ObservedRuntime(runtime, [OpenShellObserver(source)]),
    )
    registry.register("nemo-telemetry", lambda runtime: TelemetryRuntime(runtime, telemetry))
