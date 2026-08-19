"""Scheduled Hugging Face model discovery for VoxPassport.

Discovery is advisory: candidates are registered for inspection/download but are
never activated automatically.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from runtime.inference.model_registry.registry import ModelRegistry, ModelRegistryEntry
from runtime.inference.protocol import InstallationStatus, ModelCapability, RecommendationState

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryCandidate:
    upstream_id: str
    name: str
    family: str
    provider: str
    capability: ModelCapability
    languages: list[str] = field(default_factory=list)
    streaming_support: bool = False
    license_tag: str = "verify"
    estimated_size_gb: float = 0.0
    notes: str = ""

    @property
    def supports_romanian(self) -> bool:
        return "ro" in self.languages or "*" in self.languages

    @property
    def supports_english(self) -> bool:
        return "en" in self.languages or "*" in self.languages


class ModelDiscoveryAgent:
    def __init__(self, registry: ModelRegistry, scan_interval_hours: float = 24.0) -> None:
        self.registry = registry
        self.scan_interval_hours = float(scan_interval_hours)
        self._is_running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._periodic_scan_loop())

    async def stop(self) -> None:
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_discovery_pass(self) -> list[ModelRegistryEntry]:
        candidates = await self._fetch_upstream_candidates()
        promoted: list[ModelRegistryEntry] = []
        for candidate in candidates:
            entry = self._evaluate_and_convert(candidate)
            if entry is None:
                continue
            self.registry.register(entry)
            promoted.append(entry)
        logger.info("Model discovery processed %d candidates", len(candidates))
        return promoted

    @staticmethod
    def _capability_for_pipeline(pipeline_tag: str) -> Optional[ModelCapability]:
        tag = str(pipeline_tag or "").lower()
        if tag == "automatic-speech-recognition":
            return ModelCapability.ASR
        if tag in {"translation", "text2text-generation"}:
            return ModelCapability.TRANSLATION
        if tag in {"text-to-speech", "text-to-audio"}:
            return ModelCapability.TTS
        return None

    @staticmethod
    def _languages(model) -> list[str]:
        values: set[str] = set()
        for tag in getattr(model, "tags", None) or []:
            if isinstance(tag, str) and tag.startswith("language:"):
                values.add(tag.split(":", 1)[1].lower())
        card = getattr(model, "card_data", None)
        if card:
            raw = getattr(card, "language", None)
            if isinstance(raw, str):
                values.add(raw.lower())
            elif isinstance(raw, (list, tuple)):
                values.update(str(x).lower() for x in raw)
        return sorted(values)

    @staticmethod
    def _license(model) -> str:
        for tag in getattr(model, "tags", None) or []:
            if isinstance(tag, str) and tag.startswith("license:"):
                return tag.split(":", 1)[1]
        return "verify"

    @staticmethod
    def _estimated_size_gb(model) -> float:
        total = 0
        for sibling in getattr(model, "siblings", None) or []:
            size = getattr(sibling, "size", None)
            name = str(getattr(sibling, "rfilename", ""))
            if size and any(name.endswith(ext) for ext in (".safetensors", ".bin", ".gguf", ".nemo")):
                total += int(size)
        return round(total / 1024**3, 2) if total else 0.0

    @staticmethod
    def _list_models(api, task: str):
        kwargs = dict(filter=task, sort="downloads", limit=30, full=True)
        try:
            return api.list_models(direction=-1, **kwargs)
        except TypeError:
            # Keep discovery compatible with older huggingface-hub installations
            # whose list_models signature predates the direction keyword.
            return api.list_models(**kwargs)

    def _fetch_hf_blocking(self) -> list[DiscoveryCandidate]:
        from huggingface_hub import HfApi

        api = HfApi()
        discovered: dict[str, DiscoveryCandidate] = {}
        for task in ("automatic-speech-recognition", "translation", "text-to-speech"):
            try:
                for model in self._list_models(api, task):
                    model_id = str(getattr(model, "id", "") or "").strip()
                    if not model_id:
                        continue
                    capability = self._capability_for_pipeline(getattr(model, "pipeline_tag", None) or task)
                    if capability is None:
                        continue
                    provider = model_id.split("/", 1)[0] if "/" in model_id else "community"
                    discovered[model_id] = DiscoveryCandidate(
                        upstream_id=model_id,
                        name=model_id.split("/")[-1],
                        family=model_id.split("/")[-1].lower(),
                        provider=provider,
                        capability=capability,
                        languages=self._languages(model),
                        streaming_support=any(
                            "stream" in str(tag).lower()
                            for tag in (getattr(model, "tags", None) or [])
                        ),
                        license_tag=self._license(model),
                        estimated_size_gb=self._estimated_size_gb(model),
                        notes=f"Discovered from Hugging Face task index: {task}",
                    )
            except Exception as exc:
                logger.warning("Hugging Face discovery failed for %s: %s", task, exc)
        return list(discovered.values())

    async def _fetch_upstream_candidates(self) -> list[DiscoveryCandidate]:
        return await asyncio.to_thread(self._fetch_hf_blocking)

    def _evaluate_and_convert(self, candidate: DiscoveryCandidate) -> Optional[ModelRegistryEntry]:
        model_id = candidate.upstream_id.replace("/", "-").lower()
        existing = self.registry.get_entry(model_id)
        if existing and existing.installation_status == InstallationStatus.INSTALLED:
            return None

        languages = candidate.languages or ["*"]
        rec = RecommendationState.CANDIDATE
        if candidate.supports_romanian and candidate.supports_english:
            rec = RecommendationState.RECOMMENDED_FOR_LOCAL_BENCHMARK
        license_lower = candidate.license_tag.lower()
        commercial = "yes" if license_lower in {"mit", "apache-2.0", "bsd", "cc-by-4.0"} else "verify"
        return ModelRegistryEntry(
            model_id=model_id,
            name=candidate.name,
            family=candidate.family,
            provider=candidate.provider,
            capability=candidate.capability,
            upstream_id=candidate.upstream_id,
            revision="main",
            supported_source_languages=languages,
            supported_target_languages=languages,
            supports_english=candidate.supports_english,
            supports_romanian=candidate.supports_romanian,
            streaming_support=candidate.streaming_support,
            voice_cloning_support=(candidate.capability == ModelCapability.TTS),
            cross_lingual_voice_cloning=False,
            required_runtime="pytorch_or_transformers",
            min_runtime_version="",
            quantization_options=[],
            estimated_download_size_gb=candidate.estimated_size_gb,
            installed_size_gb=None,
            expected_vram_tiers={},
            expected_ram_gb=None,
            license=candidate.license_tag,
            commercial_use=commercial,
            redistribution="verify",
            trust_level="UNVERIFIED",
            recommendation_state=rec,
        )

    async def _periodic_scan_loop(self) -> None:
        while self._is_running:
            try:
                await self.run_discovery_pass()
            except Exception:
                logger.exception("Model discovery pass failed")
            try:
                await asyncio.sleep(self.scan_interval_hours * 3600)
            except asyncio.CancelledError:
                break
