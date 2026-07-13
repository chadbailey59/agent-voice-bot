import pytest

from agent_voice_bot.config import AgentLoopConfig, AppConfig
from agent_voice_bot.application import build_application_runtime, build_env_feature_registry
from agent_voice_bot.features import FeatureRegistry
from agent_voice_bot.runtimes.factory import RuntimeFactory, build_runtime
from agent_voice_bot.services.speech import SpeechStack, SpeechStackFactory
from agent_voice_bot.services.voice import VoiceServiceFactory


@pytest.mark.parametrize(
    ("mode", "streaming", "steering", "cancellation", "continuation"),
    [
        ("mock", False, False, True, False),
        ("rest", False, False, True, False),
        ("openai", False, False, True, False),
        ("mcp", False, False, True, False),
        ("hermes", True, False, True, True),
        ("nemohermes", False, False, False, True),
        ("deepagents", False, False, True, False),
        ("openclaw", True, True, True, True),
    ],
)
def test_runtime_configuration_capability_matrix(
    mode, streaming, steering, cancellation, continuation
):
    capabilities = build_runtime(AgentLoopConfig(mode=mode)).capabilities
    assert capabilities.streaming is streaming
    assert capabilities.steering is steering
    assert capabilities.cancellation is cancellation
    assert capabilities.session_continuation is continuation


def test_app_config_reads_composable_provider_and_feature_env(monkeypatch):
    monkeypatch.setenv("SPEECH_PROVIDER", "nvidia-riva")
    monkeypatch.setenv("VOICE_PROVIDER", "nemo-router")
    monkeypatch.setenv("AGENT_VOICE_FEATURES", "openshell-events, nemo-telemetry")
    monkeypatch.setenv("AGENT_LOOP_MODE", "openclaw")
    config = AppConfig.from_env()
    assert config.speech_provider == "nvidia-riva"
    assert config.voice_provider == "nemo-router"
    assert config.features == ("openshell-events", "nemo-telemetry")
    assert config.agent.mode == "openclaw"


def test_agent_mode_override_wins_over_normal_environment(monkeypatch):
    monkeypatch.setenv("AGENT_LOOP_MODE", "openclaw")
    monkeypatch.setenv("AGENT_LOOP_MODE_OVERRIDE", "mock")
    assert AgentLoopConfig.from_env().mode == "mock"


def test_runtime_factory_accepts_third_party_runtime():
    marker = object()
    factory = RuntimeFactory()
    factory.register("custom", lambda config: marker)
    assert factory.build(AgentLoopConfig(mode="custom")) is marker


def test_runtime_factory_rejects_duplicate_registration():
    factory = RuntimeFactory()
    factory.register("custom", lambda config: object())
    with pytest.raises(ValueError, match="already registered"):
        factory.register("custom", lambda config: object())


def test_speech_factory_supports_plugin_registration_without_pipecat_changes():
    stack = SpeechStack("stt", "tts", "vad")
    factory = SpeechStackFactory()
    factory.register("test", lambda: stack)
    assert factory.build("test") is stack


def test_voice_factory_supports_plugin_registration():
    service = object()
    factory = VoiceServiceFactory()
    factory.register("test", lambda: service)
    assert factory.build("test") is service


def test_application_runtime_applies_configured_features():
    config = AppConfig(features=("marker",), agent=AgentLoopConfig(mode="mock"))
    registry = FeatureRegistry()
    seen = []
    registry.register("marker", lambda runtime: seen.append(runtime) or runtime)
    runtime = build_application_runtime(config, features=registry)
    assert runtime is seen[0]


def test_application_runtime_refuses_uninstalled_feature_bundle():
    config = AppConfig(features=("openshell-events",), agent=AgentLoopConfig(mode="mock"))
    with pytest.raises(ValueError, match="no feature registry"):
        build_application_runtime(config)


def test_environment_can_install_nemo_feature_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSHELL_EVENTS_FILE", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("AGENT_VOICE_TELEMETRY_FILE", str(tmp_path / "telemetry.jsonl"))
    registry = build_env_feature_registry()
    config = AppConfig(
        features=("openshell-events", "nemo-telemetry"),
        agent=AgentLoopConfig(mode="mock"),
    )
    assert build_application_runtime(config, features=registry).capabilities.approvals is True


@pytest.mark.parametrize("factory,name", [(SpeechStackFactory(), "bad"), (VoiceServiceFactory(), "bad")])
def test_service_factories_fail_fast_for_unknown_provider(factory, name):
    with pytest.raises(ValueError, match="Unsupported"):
        factory.build(name)
