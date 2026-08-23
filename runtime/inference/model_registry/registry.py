"""
LiveTranslator — Model Registry
================================
Persistent database of all known, installed, and active models.

Design rules (from Section 16A of plan):
  - Registry metadata is stored separately from model weight files.
  - The registry survives application upgrades.
  - Filesystem directory names are NOT the authoritative model database.
  - Business logic requests models by capability, never by concrete model name.
  - Every model is replaceable through a common capability interface.
  - Hot-swap never interrupts a committed spoken utterance.
  - On hot-swap failure, the prior known-good model is restored automatically.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from runtime.inference.protocol import (
    HotSwapState,
    InstallationStatus,
    LanguageCode,
    ModelCapability,
    RecommendationState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry Entry
# ---------------------------------------------------------------------------

@dataclass
class ModelRegistryEntry:
    """Complete metadata for one registered model."""

    # Identity
    model_id: str
    name: str
    family: str
    provider: str
    capability: ModelCapability

    # Source
    upstream_id: str
    revision: str

    # Language support
    supported_source_languages: list[str]
    supported_target_languages: list[str]
    supports_english: bool
    supports_romanian: bool

    # Features
    streaming_support: bool
    voice_cloning_support: bool
    cross_lingual_voice_cloning: bool

    # Runtime
    required_runtime: str
    min_runtime_version: str
    quantization_options: list[str]

    # Size
    estimated_download_size_gb: float
    installed_size_gb: Optional[float]

    # Resources
    expected_vram_tiers: dict[str, str]
    expected_ram_gb: Optional[float]

    # Licensing
    license: str
    commercial_use: str   # "yes" | "no" | "verify" | "research_only"
    redistribution: str   # "yes" | "no" | "verify"

    # Benchmarks
    upstream_benchmarks: dict[str, Any] = field(default_factory=dict)
    local_benchmarks: dict[str, Any] = field(default_factory=dict)

    # State
    installation_status: InstallationStatus = InstallationStatus.NOT_INSTALLED
    last_used: Optional[float] = None
    last_benchmarked: Optional[float] = None
    is_active: bool = False
    is_pinned: bool = False
    eligible_for_cleanup: bool = True
    # Controls whether an otherwise known model appears in Active Engines.
    # Model Hub continues to expose it for download or cloud configuration.
    is_pipeline_enabled: bool = True

    # Trust
    requires_remote_code: bool = False
    trust_level: str = "UNVERIFIED"  # OFFICIAL_VERIFIED | COMMUNITY_VERIFIED | USER_ADDED | UNVERIFIED

    # Recommendation state (for discovery agent)
    recommendation_state: RecommendationState = RecommendationState.IGNORE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Convert enums to their values for JSON serialization
        d["capability"] = self.capability.value
        d["installation_status"] = self.installation_status.value
        d["recommendation_state"] = self.recommendation_state.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModelRegistryEntry":
        d = dict(d)
        d["capability"] = ModelCapability(d["capability"])
        d["installation_status"] = InstallationStatus(d["installation_status"])
        d["recommendation_state"] = RecommendationState(d["recommendation_state"])
        return cls(**d)


# ---------------------------------------------------------------------------
# Known-Good Model Set
# ---------------------------------------------------------------------------

@dataclass
class KnownGoodModelSet:
    """
    A validated set of active models for all required capabilities.
    Persisted after every successful end-to-end validation.
    """
    set_id: str
    validated_at: float  # Unix timestamp
    app_version: str
    models: dict[str, str]  # slot_name → model_id
    # e.g. {"asr_en": "nemotron-3.5...", "asr_ro": "...", ...}

    SLOT_NAMES = [
        "asr_en", "asr_ro",
        "translation_en_ro", "translation_ro_en",
        "tts_ro", "tts_en",
        "vad",
    ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "KnownGoodModelSet":
        return cls(**d)


# ---------------------------------------------------------------------------
# Active Model Selection
# ---------------------------------------------------------------------------

@dataclass
class ActiveModelSelection:
    """Tracks which model is active for each slot."""
    asr_en: Optional[str] = None
    asr_ro: Optional[str] = None
    translation_en_ro: Optional[str] = None
    translation_ro_en: Optional[str] = None
    tts_ro: Optional[str] = None
    tts_en: Optional[str] = None
    vad: Optional[str] = None

    def get_slot(self, slot: str) -> Optional[str]:
        return getattr(self, slot, None)

    def set_slot(self, slot: str, model_id: Optional[str]) -> None:
        if not hasattr(self, slot):
            raise ValueError(f"Unknown slot: {slot!r}")
        setattr(self, slot, model_id)


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------

class ModelRegistry:
    """
    Persistent registry of all known, installed, and active models.

    The registry is loaded from and persisted to a JSON file.
    Model weight files are stored separately; this registry tracks only metadata.

    Usage:
        registry = ModelRegistry(registry_path=Path("~/.livetranslator/registry.json"))
        registry.load()

        # Request a model by capability:
        model_id = registry.get_active_model_id("ASR", language="en")
        entry = registry.get_entry(model_id)
    """

    def __init__(self, registry_path: Path):
        self._registry_path = Path(registry_path)
        self._entries: dict[str, ModelRegistryEntry] = {}
        self._active: ActiveModelSelection = ActiveModelSelection()
        self._known_good_sets: list[KnownGoodModelSet] = []
        self._fallback_chains: dict[str, list[str]] = {}  # slot → [model_id, ...]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load registry from disk. Creates an empty registry if file does not exist."""
        if not self._registry_path.exists():
            logger.info("Registry file not found; starting with empty registry: %s", self._registry_path)
            self._save()
            return

        try:
            with open(self._registry_path, encoding="utf-8") as f:
                data = json.load(f)
            self._entries = {
                k: ModelRegistryEntry.from_dict(v)
                for k, v in data.get("entries", {}).items()
            }
            active_data = data.get("active", {})
            for slot, model_id in active_data.items():
                self._active.set_slot(slot, model_id)
            self._known_good_sets = [
                KnownGoodModelSet.from_dict(s)
                for s in data.get("known_good_sets", [])
            ]
            self._fallback_chains = data.get("fallback_chains", {})
            logger.info("Registry loaded: %d entries from %s", len(self._entries), self._registry_path)
        except Exception:
            logger.exception("Failed to load registry from %s", self._registry_path)
            raise

    def _save(self) -> None:
        """Persist registry to disk atomically."""
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._registry_path.with_suffix(".tmp")
        data = {
            "schema_version": 1,
            "entries": {k: v.to_dict() for k, v in self._entries.items()},
            "active": {
                slot: getattr(self._active, slot)
                for slot in KnownGoodModelSet.SLOT_NAMES
            },
            "known_good_sets": [s.to_dict() for s in self._known_good_sets],
            "fallback_chains": self._fallback_chains,
        }
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp_path.replace(self._registry_path)
        logger.debug("Registry persisted to %s", self._registry_path)

    # ------------------------------------------------------------------
    # Entry management
    # ------------------------------------------------------------------

    def register(self, entry: ModelRegistryEntry) -> None:
        """Add or update a model registry entry."""
        self._entries[entry.model_id] = entry
        self._save()
        logger.info("Registered model: %s (%s)", entry.model_id, entry.capability.value)

    def get_entry(self, model_id: str) -> Optional[ModelRegistryEntry]:
        return self._entries.get(model_id)

    def list_entries(
        self,
        capability: Optional[ModelCapability] = None,
        installed_only: bool = False,
        supports_romanian: Optional[bool] = None,
        supports_english: Optional[bool] = None,
    ) -> list[ModelRegistryEntry]:
        entries = list(self._entries.values())
        if capability is not None:
            entries = [e for e in entries if e.capability == capability]
        if installed_only:
            entries = [e for e in entries if e.installation_status == InstallationStatus.INSTALLED]
        if supports_romanian is not None:
            entries = [e for e in entries if e.supports_romanian == supports_romanian]
        if supports_english is not None:
            entries = [e for e in entries if e.supports_english == supports_english]
        return entries

    def update_installation_status(
        self,
        model_id: str,
        status: InstallationStatus,
        installed_size_gb: Optional[float] = None,
    ) -> None:
        entry = self._entries.get(model_id)
        if entry is None:
            raise KeyError(f"Unknown model_id: {model_id!r}")
        entry.installation_status = status
        if installed_size_gb is not None:
            entry.installed_size_gb = installed_size_gb
        self._save()

    def mark_last_used(self, model_id: str) -> None:
        entry = self._entries.get(model_id)
        if entry:
            entry.last_used = time.time()
            self._save()

    # ------------------------------------------------------------------
    # Capability-based selection (Section 16A.2)
    # ------------------------------------------------------------------

    def get_active_model_id(
        self,
        capability: str,
        language: Optional[str] = None,
        language_pair: Optional[str] = None,
    ) -> Optional[str]:
        """
        Return the active model_id for a given capability slot.

        Business logic calls this — never model-specific names.

        Examples:
            registry.get_active_model_id("ASR", language="en")
            registry.get_active_model_id("TRANSLATION", language_pair="en-ro")
            registry.get_active_model_id("TTS", language="ro")
            registry.get_active_model_id("VAD")
        """
        slot = self._resolve_slot(capability, language=language, language_pair=language_pair)
        return self._active.get_slot(slot)

    def set_active_model(
        self,
        capability: str,
        model_id: str,
        language: Optional[str] = None,
        language_pair: Optional[str] = None,
    ) -> None:
        """Set the active model for a capability slot."""
        slot = self._resolve_slot(capability, language=language, language_pair=language_pair)
        entry = self._entries.get(model_id)
        if entry is None:
            raise KeyError(f"Unknown model_id: {model_id!r}")
        if entry.installation_status != InstallationStatus.INSTALLED:
            raise ValueError(f"Model {model_id!r} is not installed.")

        # Mark previous model as inactive
        old_id = self._active.get_slot(slot)
        if old_id and old_id in self._entries:
            self._entries[old_id].is_active = False

        self._active.set_slot(slot, model_id)
        entry.is_active = True
        self._save()
        logger.info("Active model for slot %r set to %r", slot, model_id)

    @staticmethod
    def _resolve_slot(
        capability: str,
        language: Optional[str] = None,
        language_pair: Optional[str] = None,
    ) -> str:
        cap = capability.upper()
        if cap == "ASR":
            lang = (language or "").lower().split("-")[0]
            return f"asr_{lang}"
        elif cap in ("TRANSLATION", "MT"):
            pair = (language_pair or "en_ro").lower().replace("-", "_").replace("→", "_")
            return f"translation_{pair}"
        elif cap == "TTS":
            lang = (language or "").lower().split("-")[0]
            return f"tts_{lang}"
        elif cap == "VAD":
            return "vad"
        else:
            raise ValueError(f"Unknown capability: {capability!r}")

    # ------------------------------------------------------------------
    # Fallback chains (Section 16A.4)
    # ------------------------------------------------------------------

    def get_fallback_chain(self, slot: str) -> list[str]:
        return self._fallback_chains.get(slot, [])

    def set_fallback_chain(self, slot: str, model_ids: list[str]) -> None:
        self._fallback_chains[slot] = model_ids
        self._save()

    def get_fallback_model_id(self, slot: str) -> Optional[str]:
        for model_id in self._fallback_chains.get(slot, []):
            entry = self._entries.get(model_id)
            if entry and entry.installation_status == InstallationStatus.INSTALLED:
                return model_id
        return None

    # ------------------------------------------------------------------
    # Known-Good Model Sets (Section 16G)
    # ------------------------------------------------------------------

    def save_known_good_set(self, app_version: str) -> KnownGoodModelSet:
        """
        Snapshot the current active model selection as a new known-good set.
        Called after successful end-to-end validation.
        """
        set_id = f"kgms-{uuid.uuid4().hex[:8]}"
        models = {
            slot: getattr(self._active, slot)
            for slot in KnownGoodModelSet.SLOT_NAMES
        }
        kgms = KnownGoodModelSet(
            set_id=set_id,
            validated_at=time.time(),
            app_version=app_version,
            models=models,
        )
        self._known_good_sets.append(kgms)
        self._save()
        logger.info("Saved known-good model set: %s", set_id)
        return kgms

    def get_previous_known_good_set(self) -> Optional[KnownGoodModelSet]:
        """Return the most recent known-good model set, or None if none exists."""
        if not self._known_good_sets:
            return None
        return self._known_good_sets[-1]

    def rollback_to_known_good(self, set_id: Optional[str] = None) -> Optional[KnownGoodModelSet]:
        """
        Restore the active model selection from a known-good set.
        If set_id is None, restores the most recent set.
        """
        if set_id is None:
            kgms = self.get_previous_known_good_set()
        else:
            kgms = next((s for s in self._known_good_sets if s.set_id == set_id), None)

        if kgms is None:
            logger.warning("Rollback requested but no known-good set found.")
            return None

        for slot, model_id in kgms.models.items():
            if model_id is not None:
                self._active.set_slot(slot, model_id)

        self._save()
        logger.info("Rolled back to known-good model set: %s", kgms.set_id)
        return kgms

    # ------------------------------------------------------------------
    # Storage management helpers (Section 16B.3)
    # ------------------------------------------------------------------

    def total_installed_size_gb(self) -> float:
        return sum(
            e.installed_size_gb or 0.0
            for e in self._entries.values()
            if e.installation_status == InstallationStatus.INSTALLED
        )

    def get_cleanup_candidates(self, n_days_unused: int = 90) -> list[ModelRegistryEntry]:
        """
        Return models eligible for cleanup (not pinned, not active, unused for n_days).
        """
        cutoff = time.time() - n_days_unused * 86400
        result = []
        active_ids = set(filter(None, [
            getattr(self._active, slot) for slot in KnownGoodModelSet.SLOT_NAMES
        ]))
        for entry in self._entries.values():
            if entry.is_pinned:
                continue
            if entry.model_id in active_ids:
                continue
            if not entry.eligible_for_cleanup:
                continue
            if entry.installation_status != InstallationStatus.INSTALLED:
                continue
            if entry.last_used is None or entry.last_used < cutoff:
                result.append(entry)
        return result

    def __repr__(self) -> str:
        return f"ModelRegistry(entries={len(self._entries)}, path={self._registry_path})"
