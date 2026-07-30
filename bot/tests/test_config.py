import pytest

from agent_voice_bot.config import AppConfig, OpenClawConfig

CONFIG_ENV = (
    "VOICE_PROFILE",
    "OPENCLAW_GATEWAY_URL",
    "OPENCLAW_TOKEN",
    "OPENCLAW_PASSWORD",
    "OPENCLAW_SESSION_KEY",
    "OPENCLAW_TIMEOUT_SECS",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Ignore anything the developer already exported."""
    for name in CONFIG_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_target_a_nemoclaw_sandbox_gateway(clean_env):
    config = AppConfig.from_env()
    assert config.profile == "hosted"
    # 18790 is the port a NemoClaw sandbox publishes, not OpenClaw's own 18789.
    assert config.agent.gateway_url == "ws://127.0.0.1:18790"
    assert config.agent.session_key == "agent:main:main"
    assert config.agent.token is None


def test_profile_and_gateway_come_from_the_environment(clean_env):
    clean_env.setenv("VOICE_PROFILE", "Local")
    clean_env.setenv("OPENCLAW_GATEWAY_URL", "ws://dgx.internal:18790")
    clean_env.setenv("OPENCLAW_TOKEN", "secret")
    clean_env.setenv("OPENCLAW_TIMEOUT_SECS", "600")
    config = AppConfig.from_env()
    assert config.profile == "local"
    assert config.agent.gateway_url == "ws://dgx.internal:18790"
    assert config.agent.token == "secret"
    assert config.agent.timeout_secs == 600.0


def test_unknown_profile_fails_loudly(clean_env):
    clean_env.setenv("VOICE_PROFILE", "deepgram-cartesia")
    with pytest.raises(ValueError, match="VOICE_PROFILE"):
        AppConfig.from_env()


def test_openclaw_config_is_frozen():
    with pytest.raises(Exception):
        OpenClawConfig().session_key = "other"  # type: ignore[misc]
