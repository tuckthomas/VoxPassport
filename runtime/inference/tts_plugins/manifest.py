"""Declarative TTS model manifests.

A manifest describes model identity, capabilities, driver entrypoint/options, and
its logical runtime profile. Process topology and ephemeral localhost endpoints
are owned by the TTS runtime supervisor rather than by model metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


class TtsManifestError(ValueError):
    """Raised when a TTS manifest is malformed or internally inconsistent."""


@dataclass(frozen=True)
class TtsManifest:
    path: Path
    raw: dict[str, Any]

    @property
    def schema_version(self) -> int:
        return int(self.raw["schema_version"])

    @property
    def model_id(self) -> str:
        return str(self.raw["model_id"])

    @property
    def display_name(self) -> str:
        return str(self.raw["display_name"])

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(str(v) for v in self.raw.get("aliases", []))

    @property
    def runtime_profile(self) -> str:
        return str(self.raw["runtime_profile"])

    @property
    def driver_entrypoint(self) -> str:
        return str(self.raw["driver"]["entrypoint"])

    @property
    def driver_options(self) -> dict[str, Any]:
        return dict(self.raw.get("driver", {}).get("options", {}))

    @property
    def capabilities(self) -> dict[str, Any]:
        return dict(self.raw["capabilities"])

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(str(v).lower() for v in self.raw["capabilities"].get("languages", []))

    @property
    def supports_voice_cloning(self) -> bool:
        return bool(self.raw["capabilities"].get("voice_cloning", False))

    @property
    def cross_lingual_voice_cloning(self) -> bool:
        return bool(self.raw["capabilities"].get("cross_lingual_voice_cloning", False))

    @property
    def transcript_required(self) -> bool:
        return bool(self.raw.get("voice_cloning", {}).get("reference_transcript_required", False))

    @property
    def target_conditioning_pattern(self) -> Optional[str]:
        value = self.raw.get("voice_cloning", {}).get("target_conditioning_pattern")
        return str(value) if value else None

    @property
    def native_sample_rate_hz(self) -> int:
        return int(self.raw["audio"]["sample_rate_hz"])

    @property
    def sample_format(self) -> str:
        return str(self.raw["audio"].get("sample_format", "pcm_s16le"))

    @property
    def registry(self) -> dict[str, Any]:
        return dict(self.raw.get("registry", {}))

    def target_conditioning_path(self, profile_dir: Path, language: str) -> Optional[Path]:
        pattern = self.target_conditioning_pattern
        if not pattern:
            return None
        candidate = Path(profile_dir) / pattern.format(language=str(language).lower())
        return candidate if candidate.exists() else None

    @classmethod
    def load(cls, path: Path | str) -> "TtsManifest":
        manifest_path = Path(path)
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TtsManifestError(f"Could not read TTS manifest {manifest_path}: {exc}") from exc
        validate_manifest(raw, manifest_path)
        return cls(path=manifest_path, raw=raw)


def _require(mapping: dict[str, Any], key: str, *, where: str) -> Any:
    if key not in mapping:
        raise TtsManifestError(f"Missing required {where}.{key}")
    return mapping[key]


def validate_manifest(raw: dict[str, Any], path: Path | str = "<memory>") -> None:
    if not isinstance(raw, dict):
        raise TtsManifestError(f"TTS manifest {path} must contain a JSON object")
    if int(_require(raw, "schema_version", where="manifest")) != 2:
        raise TtsManifestError(f"Unsupported TTS manifest schema in {path}; expected schema_version=2")
    model_id = str(_require(raw, "model_id", where="manifest")).strip()
    display_name = str(_require(raw, "display_name", where="manifest")).strip()
    runtime_profile = str(_require(raw, "runtime_profile", where="manifest")).strip()
    if not model_id or not display_name or not runtime_profile:
        raise TtsManifestError(
            f"TTS manifest {path} requires non-empty model_id, display_name, and runtime_profile"
        )
    if "worker" in raw:
        raise TtsManifestError(
            f"TTS manifest {path} must not contain worker topology; endpoints are supervisor-owned"
        )

    driver = _require(raw, "driver", where="manifest")
    capabilities = _require(raw, "capabilities", where="manifest")
    audio = _require(raw, "audio", where="manifest")
    if not isinstance(driver, dict) or not isinstance(capabilities, dict) or not isinstance(audio, dict):
        raise TtsManifestError(f"TTS manifest {path} has invalid driver/capabilities/audio sections")
    entrypoint = str(_require(driver, "entrypoint", where="driver")).strip()
    if ":" not in entrypoint:
        raise TtsManifestError(f"driver.entrypoint in {path} must use 'module:ClassName' syntax")

    languages = capabilities.get("languages", [])
    if not isinstance(languages, list) or not languages:
        raise TtsManifestError(f"capabilities.languages in {path} must be a non-empty list")
    sample_rate = int(_require(audio, "sample_rate_hz", where="audio"))
    if sample_rate <= 0:
        raise TtsManifestError(f"audio.sample_rate_hz in {path} must be positive")
    if str(audio.get("sample_format", "pcm_s16le")) != "pcm_s16le":
        raise TtsManifestError(f"TTS manifest {path} currently supports only pcm_s16le worker output")


class TtsManifestCatalog:
    """Loads manifests and resolves model IDs/aliases without daemon branches."""

    def __init__(self, manifest_dir: Path | str | None = None) -> None:
        if manifest_dir is None:
            project_root = Path(__file__).resolve().parents[3]
            manifest_dir = project_root / "runtime" / "tts_manifests"
        self.manifest_dir = Path(manifest_dir)
        self._by_id: dict[str, TtsManifest] = {}
        self._aliases: dict[str, str] = {}

    def load(self) -> "TtsManifestCatalog":
        self._by_id.clear()
        self._aliases.clear()
        if not self.manifest_dir.exists():
            return self
        for path in sorted(self.manifest_dir.glob("*.json")):
            manifest = TtsManifest.load(path)
            key = manifest.model_id.lower()
            if key in self._by_id:
                raise TtsManifestError(f"Duplicate TTS manifest model_id: {manifest.model_id}")
            self._by_id[key] = manifest
            for alias in (manifest.model_id, *manifest.aliases):
                alias_key = str(alias).strip().lower()
                if alias_key in self._aliases and self._aliases[alias_key] != key:
                    raise TtsManifestError(f"Duplicate TTS manifest alias: {alias}")
                self._aliases[alias_key] = key
        return self

    def manifests(self) -> Iterable[TtsManifest]:
        return tuple(self._by_id.values())

    def resolve(self, model_id: str) -> TtsManifest:
        key = str(model_id or "").strip().lower()
        canonical = self._aliases.get(key, key)
        manifest = self._by_id.get(canonical)
        if manifest is None:
            raise KeyError(f"No TTS manifest registered for {model_id!r}")
        return manifest

    def resolve_optional(self, model_id: str | None) -> Optional[TtsManifest]:
        try:
            return self.resolve(str(model_id or ""))
        except KeyError:
            return None
