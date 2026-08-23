"""Bridge TTS manifests into the existing ModelRegistry model schema."""

from __future__ import annotations

from runtime.inference.model_registry.registry import ModelRegistryEntry
from runtime.inference.protocol import ModelCapability
from runtime.inference.tts_plugins.manifest import TtsManifest


def manifest_registry_entry(manifest: TtsManifest) -> ModelRegistryEntry:
    meta = manifest.registry
    quantizations = tuple(str(v) for v in meta.get("quantization_options", ["default"]))
    vram = dict(meta.get("vram", {}))
    supports_en = "en" in manifest.languages or "*" in manifest.languages
    supports_ro = "ro" in manifest.languages or "*" in manifest.languages
    upstream_id = str(meta.get("upstream_id", manifest.model_id))
    required_runtime = ["tts-driver", f"tts-profile:{manifest.runtime_profile}"]
    if manifest.backend_runtime:
        required_runtime.append(f"tts-backend-runtime:{manifest.backend_runtime}")
    return ModelRegistryEntry(
        model_id=manifest.model_id,
        name=manifest.display_name,
        family=str(meta.get("family", manifest.model_id)),
        provider=str(meta.get("provider", "unknown")),
        capability=ModelCapability.TTS,
        upstream_id=upstream_id,
        revision=str(meta.get("revision", "main")),
        quantization_options=quantizations,
        default_quantization=str(meta.get("default_quantization", quantizations[0] if quantizations else "default")),
        download_gb=float(meta.get("download_gb", 0.0)),
        vram_gb_by_quantization=vram,
        ram_gb=float(meta.get("ram_gb", 0.0)),
        supports_english=supports_en,
        supports_romanian=supports_ro,
        streaming_support=bool(manifest.capabilities.get("streaming", True)),
        voice_cloning_support=manifest.supports_voice_cloning,
        required_runtime=tuple(required_runtime),
        license=str(meta.get("license", "unknown")),
        commercial_use=str(meta.get("commercial_use", "verify")),
        redistribution=str(meta.get("redistribution", "verify")),
        trust_level=str(meta.get("trust_level", "MANIFEST")),
        recommendation=str(meta.get("recommendation", "CANDIDATE")),
        source_url=str(meta.get("source_url", f"https://huggingface.co/{upstream_id}")),
        license_url=str(meta.get("license_url", "")),
        readme_summary=str(meta.get("readme_summary", f"Manifest-driven TTS plugin using {manifest.driver_entrypoint}")),
        tags=tuple(str(v) for v in meta.get("tags", ["tts", "plugin", "voice-cloning"])),
        languages=manifest.languages,
        model_type=str(meta.get("model_type", "text-to-speech")),
        library_name=str(meta.get("library_name", "voxpassport-tts-plugin")),
        created_at=str(meta.get("created_at", "")),
        last_modified=str(meta.get("last_modified", "")),
        downloads=int(meta.get("downloads", 0)),
        likes=int(meta.get("likes", 0)),
        resolved_revision=str(meta.get("resolved_revision", "")),
        artifact=str(meta.get("artifact", "")),
        provenance=dict(meta.get("provenance", {})),
    )
