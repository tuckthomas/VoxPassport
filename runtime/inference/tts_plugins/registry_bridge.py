"""Bridge declarative TTS manifests into the existing model registry."""

from __future__ import annotations

from runtime.inference.model_registry.registry import ModelRegistryEntry
from runtime.inference.protocol import ModelCapability, RecommendationState
from runtime.inference.tts_plugins.manifest import TtsManifest


def manifest_registry_entry(
    manifest: TtsManifest,
    existing: ModelRegistryEntry | None = None,
) -> ModelRegistryEntry:
    meta = manifest.registry
    recommendation_raw = str(meta.get("recommendation", "CANDIDATE"))
    try:
        recommendation = RecommendationState(recommendation_raw)
    except ValueError:
        recommendation = RecommendationState.CANDIDATE

    entry = ModelRegistryEntry(
        model_id=manifest.model_id,
        name=manifest.display_name,
        family=str(meta.get("family", manifest.model_id)),
        provider=str(meta.get("provider", "manifest-plugin")),
        capability=ModelCapability.TTS,
        upstream_id=str(meta.get("upstream_id", "")),
        revision=str(meta.get("revision", "main")),
        supported_source_languages=[],
        supported_target_languages=list(manifest.languages),
        supports_english="en" in manifest.languages or "*" in manifest.languages,
        supports_romanian="ro" in manifest.languages or "*" in manifest.languages,
        streaming_support=bool(manifest.capabilities.get("streaming", True)),
        voice_cloning_support=manifest.supports_voice_cloning,
        cross_lingual_voice_cloning=manifest.cross_lingual_voice_cloning,
        required_runtime="voxpassport.tts.v1",
        min_runtime_version="1",
        quantization_options=list(meta.get("quantization_options", [])),
        estimated_download_size_gb=float(meta.get("download_gb", 0.0)),
        installed_size_gb=None,
        expected_vram_tiers=dict(meta.get("vram", {})),
        expected_ram_gb=(float(meta["ram_gb"]) if meta.get("ram_gb") is not None else None),
        license=str(meta.get("license", "verify")),
        commercial_use=str(meta.get("commercial_use", "verify")),
        redistribution=str(meta.get("redistribution", "verify")),
        trust_level=str(meta.get("trust_level", "COMMUNITY_VERIFIED")),
        recommendation_state=recommendation,
    )
    if existing is not None:
        entry.installation_status = existing.installation_status
        entry.installed_size_gb = existing.installed_size_gb
        entry.last_used = existing.last_used
        entry.last_benchmarked = existing.last_benchmarked
        entry.is_active = existing.is_active
        entry.is_pinned = existing.is_pinned
        entry.eligible_for_cleanup = existing.eligible_for_cleanup
        entry.is_pipeline_enabled = existing.is_pipeline_enabled
        entry.local_benchmarks = dict(existing.local_benchmarks)
    return entry
