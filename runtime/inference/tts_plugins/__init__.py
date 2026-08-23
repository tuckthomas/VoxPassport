"""Manifest-driven TTS plugin support for VoxPassport."""

from runtime.inference.tts_plugins.manifest import TtsManifest, TtsManifestCatalog
from runtime.inference.tts_plugins.registry_bridge import manifest_registry_entry

__all__ = ["TtsManifest", "TtsManifestCatalog", "manifest_registry_entry"]
