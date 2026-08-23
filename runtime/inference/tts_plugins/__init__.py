"""Manifest-driven TTS plugin, backend-runtime, and runtime-profile support."""

from runtime.inference.tts_plugins.backend_runtime import BackendRuntime, BackendRuntimeCatalog
from runtime.inference.tts_plugins.manifest import TtsManifest, TtsManifestCatalog
from runtime.inference.tts_plugins.registry_bridge import manifest_registry_entry
from runtime.inference.tts_plugins.runtime_profiles import RuntimeProfile, RuntimeProfileCatalog
from runtime.inference.tts_plugins.runtime_supervisor import TtsRuntimeSupervisor, get_tts_runtime_supervisor
from runtime.inference.tts_plugins.runtime_cleanup import register_runtime_cleanup

register_runtime_cleanup()

__all__ = [
    "BackendRuntime",
    "BackendRuntimeCatalog",
    "TtsManifest",
    "TtsManifestCatalog",
    "manifest_registry_entry",
    "RuntimeProfile",
    "RuntimeProfileCatalog",
    "TtsRuntimeSupervisor",
    "get_tts_runtime_supervisor",
]
