"""Optional NemoClaw/OpenShell integration package."""

from agent_voice_bot.nemo.observer import OpenShellEventSource, OpenShellObserver
from agent_voice_bot.nemo.features import register_nemo_features
from agent_voice_bot.nemo.file_source import JsonlEventSource

__all__ = [
    "JsonlEventSource", "OpenShellEventSource", "OpenShellObserver",
    "register_nemo_features",
]
