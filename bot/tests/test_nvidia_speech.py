import pytest

from agent_voice_bot.services.speech import default_speech_factory

pytest.importorskip(
    "riva.client",
    reason="local NVIDIA speech stack needs the optional `nvidia` extra",
)

NVIDIA_ENV = (
    "NVIDIA_API_KEY",
    "NVIDIA_ASR_SERVER",
    "NVIDIA_ASR_MODEL",
    "NVIDIA_ASR_USE_SSL",
    "NVIDIA_TTS_SERVER",
    "NVIDIA_TTS_MODEL",
    "NVIDIA_TTS_USE_SSL",
    "NVIDIA_TTS_VOICE",
    "NVIDIA_TTS_FUNCTION_ID",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Ignore any NVIDIA settings the developer already exported."""
    for name in NVIDIA_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_target_a_local_deployment_without_credentials(clean_env):
    stack = default_speech_factory().build("nvidia-riva")
    assert stack.stt._server == "localhost:50051"
    assert stack.tts._server == "localhost:50052"
    # A local NIM terminates plaintext gRPC and authenticates nothing, so
    # cloud-only SSL and NVCF function routing must both stay off.
    assert stack.stt._use_ssl is False
    assert stack.tts._use_ssl is False
    assert stack.stt._api_key is None
    assert stack.tts._function_id == ""


def test_tts_sends_no_bearer_none_when_unauthenticated(clean_env):
    # NvidiaTTSService interpolates the key into the authorization header
    # unconditionally, so None would reach the server as "Bearer None".
    assert default_speech_factory().build("nvidia-riva").tts._api_key == ""


def test_default_asr_model_label_names_a_streaming_deployment(clean_env):
    # parakeet-0.6b-tdt ships offline-only profiles; the default must name a
    # NIM that can actually stream, or the voice loop gets no transcripts.
    model = default_speech_factory().build("nvidia-riva").stt._settings.model
    assert model == "parakeet-1.1b-en-US-asr-streaming"


def test_environment_overrides_servers_and_models(clean_env):
    clean_env.setenv("NVIDIA_ASR_SERVER", "gpu-box:50051")
    clean_env.setenv("NVIDIA_TTS_SERVER", "gpu-box:50052")
    clean_env.setenv("NVIDIA_ASR_MODEL", "parakeet-ctc-1.1b")
    clean_env.setenv("NVIDIA_TTS_MODEL", "fastpitch-hifigan-en-us")
    stack = default_speech_factory().build("nvidia-riva")
    assert stack.stt._server == "gpu-box:50051"
    assert stack.tts._server == "gpu-box:50052"
    assert stack.stt._settings.model == "parakeet-ctc-1.1b"
    assert stack.tts._settings.model == "fastpitch-hifigan-en-us"


def test_ssl_can_be_re_enabled_for_a_remote_endpoint(clean_env):
    clean_env.setenv("NVIDIA_ASR_USE_SSL", "true")
    clean_env.setenv("NVIDIA_TTS_USE_SSL", "1")
    clean_env.setenv("NVIDIA_API_KEY", "nvapi-secret")
    stack = default_speech_factory().build("nvidia-riva")
    assert stack.stt._use_ssl is True
    assert stack.tts._use_ssl is True
    assert stack.stt._api_key == "nvapi-secret"


def test_unset_voice_keeps_the_default_that_matches_the_default_model(clean_env):
    voice = default_speech_factory().build("nvidia-riva").tts._settings.voice
    assert voice == "Magpie-Multilingual.EN-US.Aria"


def test_voice_override_applies(clean_env):
    clean_env.setenv("NVIDIA_TTS_VOICE", "English-US.Female-1")
    stack = default_speech_factory().build("nvidia-riva")
    assert stack.tts._settings.voice == "English-US.Female-1"


def test_streaming_asr_emits_interim_results(clean_env):
    # Interim transcripts are what let the voice loop interrupt early.
    assert default_speech_factory().build("nvidia-riva").stt._settings.interim_results is True
