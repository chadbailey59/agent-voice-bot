"""Optional NemoClaw/OpenShell integration package."""

from agent_voice_bot.nemo.features import register_nemo_features
from agent_voice_bot.nemo.file_source import JsonlEventSource
from agent_voice_bot.nemo.observer import OpenShellEventSource, OpenShellObserver

__all__ = [
    "JsonlEventSource", "OpenShellEventSource", "OpenShellObserver",
    "register_nemo_features",
]
