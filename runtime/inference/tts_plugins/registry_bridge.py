"""Bridge TTS manifests into the current ModelRegistry schema."""

from __future__ import annotations

from runtime.inference.model_registry.registry import ModelRegistryEntry
from runtime.inference.protocol import (
    InstallationStatus,
    ModelCapability,
    RecommendationState,
)
from runtime.inference.tts_plugins.manifest import TtsManifest


def _recommendation(value: object) -> RecommendationState:
    try:
        return RecommendationState(str(value or "CANDIDATE"))
    except ValueError:
        return RecommendationState.CANDIDATE


def manifest_registry_entry(
    manifest: TtsManifest,
    existing: ModelRegistryEntry | None = None,
) -> ModelRegistryEntry:
    """Project manifest-owned TTS metadata into ``ModelRegistryEntry``.

    Discovery metadata belongs to the manifest, while mutable installation/use
    state belongs to the registry. Re-registering a manifest during daemon
    startup therefore refreshes metadata without erasing installed/active state.
    """

    meta = manifest.registry
    quantizations = [str(v) for v in meta.get("quantization_options", ["default"])]
    vram = {str(k): str(v) for k, v in dict(meta.get("vram", {})).items()}
    languages = [str(value).lower() for value in manifest.languages]
    supports_en = "en" in languages or "*" in languages
    supports_ro = "ro" in languages or "*" in languages
    upstream_id = str(meta.get("upstream_id", manifest.model_id))

    runtime_parts = ["tts-driver", f"tts-profile:{manifest.runtime_profile}"]
    if manifest.backend_runtime:
        runtime_parts.append(f"tts-backend-runtime:{manifest.backend_runtime}")

    return ModelRegistryEntry(
        model_id=manifest.model_id,
        name=manifest.display_name,
        family=str(meta.get("family", manifest.model_id)),
        provider=str(meta.get("provider", "unknown")),
        capability=ModelCapability.TTS,
        upstream_id=upstream_id,
        revision=str(meta.get("revision", "main")),
        supported_source_languages=languages,
        supported_target_languages=languages,
        supports_english=supports_en,
        supports_romanian=supports_ro,
        streaming_support=bool(manifest.capabilities.get("streaming", True)),
        voice_cloning_support=manifest.supports_voice_cloning,
        cross_lingual_voice_cloning=manifest.cross_lingual_voice_cloning,
        required_runtime=";".join(runtime_parts),
        min_runtime_version=str(meta.get("min_runtime_version", "")),
        quantization_options=quantizations,
        estimated_download_size_gb=float(meta.get("download_gb", 0.0)),
        installed_size_gb=(
            existing.installed_size_gb if existing is not None else None
        ),
        expected_vram_tiers=vram,
        expected_ram_gb=(
            float(meta["ram_gb"]) if meta.get("ram_gb") is not None else None
        ),
        license=str(meta.get("license", "unknown")),
        commercial_use=str(meta.get("commercial_use", "verify")),
        redistribution=str(meta.get("redistribution", "verify")),
        upstream_benchmarks=(
            dict(existing.upstream_benchmarks) if existing is not None else {}
        ),
        local_benchmarks=(
            dict(existing.local_benchmarks) if existing is not None else {}
        ),
        installation_status=(
            existing.installation_status
            if existing is not None
            else InstallationStatus.NOT_INSTALLED
        ),
        last_used=existing.last_used if existing is not None else None,
        last_benchmarked=existing.last_benchmarked if existing is not None else None,
        is_active=existing.is_active if existing is not None else False,
        is_pinned=existing.is_pinned if existing is not None else False,
        eligible_for_cleanup=(
            existing.eligible_for_cleanup if existing is not None else True
        ),
        is_pipeline_enabled=(
            existing.is_pipeline_enabled if existing is not None else True
        ),
        requires_remote_code=bool(meta.get("requires_remote_code", False)),
        trust_level=str(meta.get("trust_level", "MANIFEST")),
        recommendation_state=_recommendation(meta.get("recommendation")),
    )
