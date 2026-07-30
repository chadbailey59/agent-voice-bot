import pytest

from agent_voice_bot.services import build_voice_stack

PROFILE_ENV = (
    "DEEPGRAM_API_KEY",
    "BASETEN_API_KEY",
    "BASETEN_BASE_URL",
    "BASETEN_MODEL",
    "GRADIUM_API_KEY",
    "GRADIUM_VOICE_ID",
    "NVIDIA_API_KEY",
    "NVIDIA_ASR_SERVER",
    "NVIDIA_ASR_MODEL",
    "NVIDIA_ASR_USE_SSL",
    "NVIDIA_LLM_BASE_URL",
    "NVIDIA_LLM_MODEL",
    "NVIDIA_TTS_SERVER",
    "NVIDIA_TTS_MODEL",
    "NVIDIA_TTS_USE_SSL",
    "NVIDIA_TTS_VOICE",
    "NVIDIA_TTS_FUNCTION_ID",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Ignore any provider settings the developer already exported."""
    for name in PROFILE_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="VOICE_PROFILE"):
        build_voice_stack("nvidia-riva")


def test_hosted_profile_wires_deepgram_baseten_and_gradium(clean_env):
    clean_env.setenv("DEEPGRAM_API_KEY", "dg")
    clean_env.setenv("BASETEN_API_KEY", "bt")
    clean_env.setenv("GRADIUM_API_KEY", "gr")

    stack = build_voice_stack("hosted")

    assert type(stack.stt).__name__ == "DeepgramSTTService"
    assert type(stack.llm).__name__ == "BasetenLLMService"
    assert type(stack.tts).__name__ == "GradiumTTSService"
    # Nemotron, not the service's own Kimi default.
    assert stack.llm._settings.model.startswith("nvidia/NVIDIA-Nemotron")


def test_hosted_profile_takes_a_dedicated_deployment_from_the_environment(clean_env):
    clean_env.setenv("DEEPGRAM_API_KEY", "dg")
    clean_env.setenv("BASETEN_API_KEY", "bt")
    clean_env.setenv("GRADIUM_API_KEY", "gr")
    clean_env.setenv("BASETEN_BASE_URL", "https://model-abc.api.baseten.co/environments/production/sync/v1")
    clean_env.setenv("BASETEN_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano")

    stack = build_voice_stack("hosted")

    assert stack.llm._settings.model == "nvidia/NVIDIA-Nemotron-3-Nano"


def test_hosted_profile_fails_loudly_without_its_keys(clean_env):
    with pytest.raises(KeyError):
        build_voice_stack("hosted")


class TestLocalProfile:
    @pytest.fixture(autouse=True)
    def _needs_riva(self):
        pytest.importorskip(
            "riva.client",
            reason="the local profile needs the optional `nvidia` extra",
        )

    def test_defaults_target_a_local_deployment_without_credentials(self, clean_env):
        stack = build_voice_stack("local")

        assert stack.stt._server == "localhost:50051"
        assert stack.tts._server == "localhost:50052"
        # A local NIM terminates plaintext gRPC and authenticates nothing, so
        # cloud-only SSL and NVCF function routing must both stay off.
        assert stack.stt._use_ssl is False
        assert stack.tts._use_ssl is False
        assert stack.stt._api_key is None
        assert stack.tts._function_id == ""

    def test_llm_points_at_a_self_hosted_nim_not_nvidias_cloud(self, clean_env):
        stack = build_voice_stack("local")

        assert type(stack.llm).__name__ == "NvidiaLLMService"
        assert "api.nvidia.com" not in str(stack.llm._client.base_url)
        assert stack.llm._settings.model == "nvidia/nvidia-nemotron-3-nano"

    def test_servers_and_model_come_from_the_environment(self, clean_env):
        clean_env.setenv("NVIDIA_ASR_SERVER", "dgx:9001")
        clean_env.setenv("NVIDIA_TTS_SERVER", "dgx:9002")
        clean_env.setenv("NVIDIA_LLM_BASE_URL", "http://dgx:8000/v1")
        clean_env.setenv("NVIDIA_LLM_MODEL", "nvidia/nvidia-nemotron-3-super")

        stack = build_voice_stack("local")

        assert stack.stt._server == "dgx:9001"
        assert stack.tts._server == "dgx:9002"
        assert stack.llm._settings.model == "nvidia/nvidia-nemotron-3-super"
