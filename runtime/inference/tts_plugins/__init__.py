"""Manifest-driven TTS plugin and runtime-profile support for VoxPassport."""

from runtime.inference.tts_plugins.manifest import TtsManifest, TtsManifestCatalog
from runtime.inference.tts_plugins.registry_bridge import manifest_registry_entry
from runtime.inference.tts_plugins.runtime_profiles import RuntimeProfile, RuntimeProfileCatalog
from runtime.inference.tts_plugins.runtime_supervisor import TtsRuntimeSupervisor, get_tts_runtime_supervisor

__all__ = [
    "TtsManifest",
    "TtsManifestCatalog",
    "manifest_registry_entry",
    "RuntimeProfile",
    "RuntimeProfileCatalog",
    "TtsRuntimeSupervisor",
    "get_tts_runtime_supervisor",
]
