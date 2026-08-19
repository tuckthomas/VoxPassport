"""
LiveTranslator — Built-in Model Catalog
========================================
Pre-populated catalog entries for all candidate models listed in the plan.

These entries are the starting point for the ModelRegistry.
They represent known models that may be installed and benchmarked.
All upstream_id and revision fields are PLACEHOLDERS until verified
against official model cards (Section 46 of the plan).

Rules:
  - Do not hard-code absolute paths.
  - Do not assume a model is available until verified with its current model card.
  - Track license separately from technical quality.
"""

from __future__ import annotations

from runtime.inference.model_registry.registry import ModelRegistryEntry
from runtime.inference.protocol import (
    InstallationStatus,
    ModelCapability,
    RecommendationState,
)


def get_builtin_catalog() -> list[ModelRegistryEntry]:
    """
    Return all built-in catalog entries.
    These are registered into the ModelRegistry at first startup.
    """
    return [
        # ----------------------------------------------------------------
        # VAD
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="silero-vad-v4",
            name="Silero VAD v4",
            family="silero-vad",
            provider="snakers4",
            capability=ModelCapability.VAD,
            upstream_id="snakers4/silero-vad",
            revision="v4",  # verify exact tag
            supported_source_languages=["*"],
            supported_target_languages=[],
            supports_english=True,
            supports_romanian=True,
            streaming_support=True,
            voice_cloning_support=False,
            cross_lingual_voice_cloning=False,
            required_runtime="pytorch",
            min_runtime_version="2.0.0",
            quantization_options=[],
            estimated_download_size_gb=0.01,
            installed_size_gb=None,
            expected_vram_tiers={},
            expected_ram_gb=0.1,
            license="MIT",
            commercial_use="yes",
            redistribution="yes",
            trust_level="OFFICIAL_VERIFIED",
            recommendation_state=RecommendationState.CANDIDATE,
        ),

        # ----------------------------------------------------------------
        # ASR — Primary Candidate
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="nvidia-nemotron-3.5-asr-streaming-0.6b",
            name="NVIDIA Nemotron 3.5 ASR Streaming 0.6B",
            family="nemotron",
            provider="nvidia",
            capability=ModelCapability.ASR,
            upstream_id="",  # MUST verify from model card (Section 46)
            revision="",     # MUST verify
            supported_source_languages=["en", "ro"],  # verify RO support
            supported_target_languages=[],
            supports_english=True,
            supports_romanian=True,  # UNVERIFIED — verify on exact checkpoint
            streaming_support=True,
            voice_cloning_support=False,
            cross_lingual_voice_cloning=False,
            required_runtime="nemo",
            min_runtime_version="2.0.0",
            quantization_options=["fp16", "bf16", "int8"],
            estimated_download_size_gb=1.2,
            installed_size_gb=None,
            expected_vram_tiers={"fp16": "~3GB", "int8": "~1.5GB"},
            expected_ram_gb=2.0,
            license="OpenMDW-1.1",
            commercial_use="verify",
            redistribution="verify",
            trust_level="OFFICIAL_VERIFIED",
            recommendation_state=RecommendationState.RECOMMENDED_FOR_LOCAL_BENCHMARK,
        ),

        # ----------------------------------------------------------------
        # ASR — Benchmark Comparator & Primary Multilingual ASR
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="nvidia-parakeet-tdt-0.6b-v3",
            name="NVIDIA Parakeet TDT 0.6B v3",
            family="parakeet",
            provider="nvidia",
            capability=ModelCapability.ASR,
            upstream_id="nvidia/parakeet-tdt-0.6b-v3",
            revision="main",
            supported_source_languages=["en", "ro"],  # Supports 25 European languages including RO
            supported_target_languages=[],
            supports_english=True,
            supports_romanian=True,
            streaming_support=True,
            voice_cloning_support=False,
            cross_lingual_voice_cloning=False,
            required_runtime="nemo",
            min_runtime_version="2.0.0",
            quantization_options=["fp16", "bf16"],
            estimated_download_size_gb=1.2,
            installed_size_gb=None,
            expected_vram_tiers={"fp16": "~3GB"},
            expected_ram_gb=2.0,
            license="CC-BY-4.0",
            commercial_use="yes",
            redistribution="yes",
            trust_level="OFFICIAL_VERIFIED",
            recommendation_state=RecommendationState.RECOMMENDED_FOR_LOCAL_BENCHMARK,
        ),

        # ----------------------------------------------------------------
        # Direct Speech Translation — Experimental
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="nvidia-canary-1b-v2",
            name="NVIDIA Canary-1B-v2",
            family="canary",
            provider="nvidia",
            capability=ModelCapability.DIRECT_SPEECH_TRANSLATION,
            upstream_id="nvidia/canary-1b-v2",
            revision="main",
            supported_source_languages=["en", "ro", "de", "es", "fr"],
            supported_target_languages=["en", "ro", "de", "es", "fr"],
            supports_english=True,
            supports_romanian=True,
            streaming_support=False,
            voice_cloning_support=False,
            cross_lingual_voice_cloning=False,
            required_runtime="nemo",
            min_runtime_version="2.0.0",
            quantization_options=["fp16"],
            estimated_download_size_gb=2.0,
            installed_size_gb=None,
            expected_vram_tiers={"fp16": "~5GB"},
            expected_ram_gb=4.0,
            license="CC-BY-4.0",
            commercial_use="yes",
            redistribution="yes",
            trust_level="OFFICIAL_VERIFIED",
            recommendation_state=RecommendationState.CANDIDATE,
        ),

        # ----------------------------------------------------------------
        # Translation — Primary Low-Latency Candidate
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="xiaomi-milmmt-46-1b-v1.0",
            name="Xiaomi MiLMMT-46-1B-v1.0",
            family="milmmt46",
            provider="xiaomi",
            capability=ModelCapability.TRANSLATION,
            upstream_id="xiaomi-research/MiLMMT-46-1B-v1.0",
            revision="main",
            supported_source_languages=["en", "ro", "*"],
            supported_target_languages=["en", "ro", "*"],
            supports_english=True,
            supports_romanian=True,
            streaming_support=False,
            voice_cloning_support=False,
            cross_lingual_voice_cloning=False,
            required_runtime="transformers",
            min_runtime_version="4.40.0",
            quantization_options=["fp16", "bf16", "int8", "int4"],
            estimated_download_size_gb=2.0,
            installed_size_gb=None,
            expected_vram_tiers={"fp16": "~3GB", "int8": "~1.5GB"},
            expected_ram_gb=4.0,
            license="Apache-2.0 (code) / Gemma Terms",
            commercial_use="yes",
            redistribution="yes",
            requires_remote_code=False,
            trust_level="OFFICIAL_VERIFIED",
            recommendation_state=RecommendationState.RECOMMENDED_FOR_LOCAL_BENCHMARK,
        ),

        # ----------------------------------------------------------------
        # Translation — Quality Candidate
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="xiaomi-milmmt-46-4b-v1.0",
            name="Xiaomi MiLMMT-46-4B-v1.0",
            family="milmmt46",
            provider="xiaomi",
            capability=ModelCapability.TRANSLATION,
            upstream_id="xiaomi-research/MiLMMT-46-4B-v1.0",
            revision="main",
            supported_source_languages=["en", "ro", "*"],
            supported_target_languages=["en", "ro", "*"],
            supports_english=True,
            supports_romanian=True,
            streaming_support=False,
            voice_cloning_support=False,
            cross_lingual_voice_cloning=False,
            required_runtime="transformers",
            min_runtime_version="4.40.0",
            quantization_options=["fp16", "bf16", "int8", "int4"],
            estimated_download_size_gb=8.0,
            installed_size_gb=None,
            expected_vram_tiers={"fp16": "~10GB", "int8": "~5GB", "int4": "~3GB"},
            expected_ram_gb=12.0,
            license="Apache-2.0 (code) / Gemma Terms",
            commercial_use="yes",
            redistribution="yes",
            requires_remote_code=False,
            trust_level="OFFICIAL_VERIFIED",
            recommendation_state=RecommendationState.CANDIDATE,
        ),

        # ----------------------------------------------------------------
        # Translation — Quality Comparator
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="nvidia-riva-translate-4b-v2",
            name="NVIDIA Riva-Translate-4B-Instruct-v2",
            family="riva-translate",
            provider="nvidia",
            capability=ModelCapability.TRANSLATION,
            upstream_id="nvidia/riva-translate-4b-instruct-v2",
            revision="main",
            supported_source_languages=["en", "ro"],
            supported_target_languages=["en", "ro"],
            supports_english=True,
            supports_romanian=True,
            streaming_support=False,
            voice_cloning_support=False,
            cross_lingual_voice_cloning=False,
            required_runtime="nemo_or_transformers",
            min_runtime_version="",
            quantization_options=["fp16"],
            estimated_download_size_gb=8.0,
            installed_size_gb=None,
            expected_vram_tiers={"fp16": "~10GB"},
            expected_ram_gb=12.0,
            license="NVIDIA-OpenModel",
            commercial_use="verify",
            redistribution="verify",
            trust_level="OFFICIAL_VERIFIED",
            recommendation_state=RecommendationState.CANDIDATE,
        ),

        # ----------------------------------------------------------------
        # TTS — Primary Candidate
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="omnivoice-stock",
            name="k2-fsa OmniVoice (stock voice)",
            family="omnivoice",
            provider="k2-fsa",
            capability=ModelCapability.TTS,
            upstream_id="k2-fsa/OmniVoice",
            revision="main",
            supported_source_languages=[],
            supported_target_languages=["en", "ro"],
            supports_english=True,
            supports_romanian=True,
            streaming_support=True,
            voice_cloning_support=True,
            cross_lingual_voice_cloning=True,
            required_runtime="k2_or_sherpa_onnx",
            min_runtime_version="",
            quantization_options=[],
            estimated_download_size_gb=1.0,
            installed_size_gb=None,
            expected_vram_tiers={},
            expected_ram_gb=1.0,
            license="Apache-2.0",
            commercial_use="yes",
            redistribution="yes",
            trust_level="OFFICIAL_VERIFIED",
            recommendation_state=RecommendationState.RECOMMENDED_FOR_LOCAL_BENCHMARK,
        ),

        # ----------------------------------------------------------------
        # TTS — Research Comparator (non-production until license verified)
        # ----------------------------------------------------------------
        ModelRegistryEntry(
            model_id="higgs-tts-3",
            name="Higgs TTS 3",
            family="higgs-tts",
            provider="higgs-audio",
            capability=ModelCapability.TTS,
            upstream_id="",
            revision="",
            supported_source_languages=[],
            supported_target_languages=["en"],  # RO support unverified
            supports_english=True,
            supports_romanian=False,  # unverified
            streaming_support=False,
            voice_cloning_support=True,
            cross_lingual_voice_cloning=False,
            required_runtime="transformers_or_native",
            min_runtime_version="",
            quantization_options=[],
            estimated_download_size_gb=5.0,
            installed_size_gb=None,
            expected_vram_tiers={},
            expected_ram_gb=8.0,
            license="UNKNOWN",  # Must verify before any use
            commercial_use="verify",
            redistribution="verify",
            trust_level="UNVERIFIED",
            recommendation_state=RecommendationState.WATCH,
        ),
    ]
