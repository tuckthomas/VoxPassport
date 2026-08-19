"""
LiveTranslator - Adapter Registry (Section 16F)
Maps model families to their adapter classes and validates compatibility
before any adapter is loaded into the pipeline.
"""

from __future__ import annotations

import logging
from typing import Optional, Type

from runtime.inference.model_registry.compatibility.adapter_compatibility import (
    AdapterMetadata,
    CompatibilityError,
    check_adapter_compatibility,
)

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    Registry of known adapter classes indexed by model family.

    Rules:
      - Only registered, version-checked adapters can be loaded.
      - Unknown model families raise an explicit error rather than
        falling back to arbitrary code execution.
      - Adapters are NOT instantiated until explicitly requested.
    """

    def __init__(self):
        # family -> (AdapterClass, AdapterMetadata)
        self._registry: dict[str, tuple[type, AdapterMetadata]] = {}

    def register(self, family: str, adapter_class: type, metadata: AdapterMetadata) -> None:
        """Register an adapter class for a model family."""
        try:
            check_adapter_compatibility(metadata)
        except CompatibilityError as exc:
            logger.error(
                "Refusing to register adapter '%s' for family '%s': %s",
                metadata.adapter_name, family, exc,
            )
            raise
        self._registry[family] = (adapter_class, metadata)
        logger.info(
            "Registered adapter '%s' v%s.%s for family '%s'",
            metadata.adapter_name, *metadata.adapter_version, family,
        )

    def get_adapter_class(self, family: str) -> Optional[type]:
        entry = self._registry.get(family)
        return entry[0] if entry else None

    def get_metadata(self, family: str) -> Optional[AdapterMetadata]:
        entry = self._registry.get(family)
        return entry[1] if entry else None

    def is_supported(self, family: str) -> bool:
        return family in self._registry

    def list_families(self) -> list[str]:
        return list(self._registry.keys())

    def instantiate(self, family: str, **kwargs) -> object:
        """
        Instantiate an adapter for the given model family.
        Re-checks compatibility at instantiation time.
        """
        entry = self._registry.get(family)
        if entry is None:
            raise KeyError(
                f"No adapter registered for model family '{family}'. "
                "Cannot load arbitrary code. Register an adapter first."
            )
        adapter_class, metadata = entry
        check_adapter_compatibility(metadata)   # re-check in case runtime changed
        return adapter_class(**kwargs)


# ---------------------------------------------------------------------------
# Global singleton — pre-populated with known adapters
# ---------------------------------------------------------------------------

_global_registry = AdapterRegistry()


def get_global_adapter_registry() -> AdapterRegistry:
    return _global_registry


def _register_builtin_adapters() -> None:
    """
    Register all built-in adapters with their compatibility metadata.
    Called once at application startup.
    """
    from runtime.inference.adapters.asr.nemotron35_streaming_asr_adapter import Nemotron35StreamingAsrAdapter
    from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import ParakeetTdtV3AsrAdapter
    from runtime.inference.adapters.asr.canary_v2_speech_translation_adapter import CanaryV2SpeechTranslationAdapter
    from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
    from runtime.inference.adapters.translation.riva_translate_4b_adapter import RivaTranslate4BAdapter
    from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
    from runtime.inference.adapters.vad.silero_vad_adapter import SileroVadAdapter

    adapters = [
        ("nemotron-3.5-asr-streaming", Nemotron35StreamingAsrAdapter, AdapterMetadata(
            adapter_name="Nemotron35StreamingAsrAdapter",
            adapter_version=(1, 0),
            supported_model_families=["nemotron-3.5-asr-streaming"],
            supported_capabilities=["ASR"],
            runtime_requirements={"torch": ">=2.0"},
            min_app_api_version=(1, 0),
        )),
        ("parakeet-tdt-v3", ParakeetTdtV3AsrAdapter, AdapterMetadata(
            adapter_name="ParakeetTdtV3AsrAdapter",
            adapter_version=(1, 0),
            supported_model_families=["parakeet-tdt-v3"],
            supported_capabilities=["ASR"],
            runtime_requirements={"torch": ">=2.0"},
            min_app_api_version=(1, 0),
        )),
        ("canary-1b-v2", CanaryV2SpeechTranslationAdapter, AdapterMetadata(
            adapter_name="CanaryV2SpeechTranslationAdapter",
            adapter_version=(1, 0),
            supported_model_families=["canary-1b-v2"],
            supported_capabilities=["DIRECT_SPEECH_TRANSLATION"],
            runtime_requirements={"torch": ">=2.0"},
            min_app_api_version=(1, 0),
        )),
        ("milmmt-46", MiLMMT46TranslationAdapter, AdapterMetadata(
            adapter_name="MiLMMT46TranslationAdapter",
            adapter_version=(1, 0),
            supported_model_families=["milmmt-46"],
            supported_capabilities=["TRANSLATION"],
            runtime_requirements={"torch": ">=2.0"},
            min_app_api_version=(1, 0),
        )),
        ("riva-translate-4b", RivaTranslate4BAdapter, AdapterMetadata(
            adapter_name="RivaTranslate4BAdapter",
            adapter_version=(1, 0),
            supported_model_families=["riva-translate-4b"],
            supported_capabilities=["TRANSLATION"],
            runtime_requirements={"torch": ">=2.0"},
            min_app_api_version=(1, 0),
        )),
        ("omnivoice", OmniVoiceTtsAdapter, AdapterMetadata(
            adapter_name="OmniVoiceTtsAdapter",
            adapter_version=(1, 0),
            supported_model_families=["omnivoice"],
            supported_capabilities=["TTS"],
            runtime_requirements={"torch": ">=2.0"},
            min_app_api_version=(1, 0),
        )),
        ("silero-vad", SileroVadAdapter, AdapterMetadata(
            adapter_name="SileroVadAdapter",
            adapter_version=(1, 0),
            supported_model_families=["silero-vad"],
            supported_capabilities=["VAD"],
            runtime_requirements={"torch": ">=2.0"},
            min_app_api_version=(1, 0),
        )),
    ]

    for family, cls, meta in adapters:
        try:
            _global_registry.register(family, cls, meta)
        except Exception as exc:
            logger.warning("Could not register built-in adapter for '%s': %s", family, exc)
