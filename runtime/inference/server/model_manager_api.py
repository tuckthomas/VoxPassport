"""Model-manager business logic for VoxPassport.

The controller owns canonical model IDs, installation state, and the active
runtime slots used by both the REST API and desktop Model Hub.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime.inference.model_registry.installers import DownloadManager, HuggingFaceInstaller, LocalImportInstaller
from runtime.inference.model_registry.registry import KnownGoodModelSet, ModelRegistry, ModelRegistryEntry
from runtime.inference.protocol import InstallationStatus, ModelCapability, RecommendationState

logger = logging.getLogger(__name__)


class ModelManagerController:
    NATIVE_HIGGS_MODEL_ID = "higgs-tts-3-q4_k_m"
    _ALIASES = {
        "omnivoice": "omnivoice-stock",
        "k2-fsa-omnivoice": "omnivoice-stock",
        "omnivoice-stock": "omnivoice-stock",
        "bosonai-higgs-tts-3-4b": "higgs-tts-3",
        "higgs": "higgs-tts-3",
        "higgs-tts-3": "higgs-tts-3",
        "openmoss-moss-tts-1.5": "moss-tts-1.5",
        "moss": "moss-tts-1.5",
        "moss-tts-1.5": "moss-tts-1.5",
        "openbmb-voxcpm2": "voxcpm-2",
        "voxcpm": "voxcpm-2",
        "voxcpm-2": "voxcpm-2",
        "xiaomi-milmmt-46-1b": "xiaomi-milmmt-46-1b-v1.0",
        "xiaomimilm-milmmt-46-1b-v1.0": "xiaomi-milmmt-46-1b-v1.0",
        "xiaomi-milmmt-46-1b-v1.0": "xiaomi-milmmt-46-1b-v1.0",
        "xiaomimilm-milmmt-46-4b-v1.0": "xiaomi-milmmt-46-4b-v1.0",
        "xiaomi-milmmt-46-4b": "xiaomi-milmmt-46-4b-v1.0",
        "xiaomi-milmmt-46-4b-v1.0": "xiaomi-milmmt-46-4b-v1.0",
        "silero-vad-v4": "silero-vad-v6.2.1",
        "snakers4-silero-vad": "silero-vad-v6.2.1",
        "silero-vad-v6.2.1": "silero-vad-v6.2.1",
        "nvidia-diar_streaming_sortformer_4spk-v2.1": "nvidia-diar-streaming-sortformer-4spk-v2.1",
        "facebook-omniasr-ctc-300m": "meta-omniasr-ctc-300m",
        "facebook-omniasr-ctc-1b": "meta-omniasr-ctc-1b",
    }

    _UI_IDS = {
        "omnivoice-stock": "omnivoice",
        "xiaomi-milmmt-46-1b-v1.0": "xiaomi-milmmt-46-1b",
        "xiaomi-milmmt-46-4b-v1.0": "xiaomi-milmmt-46-4b",
        "silero-vad-v4": "silero-vad-v6.2.1",
    }

    def __init__(
        self,
        registry: ModelRegistry,
        model_store_dir: Optional[str | Path] = None,
        staging_dir: Optional[str | Path] = None,
        on_progress=None,
    ) -> None:
        self.registry = registry
        self._model_store_dir = Path(model_store_dir) if model_store_dir else Path("models")
        self._staging_dir = Path(staging_dir) if staging_dir else self._model_store_dir / ".staging"
        self._external_on_progress = on_progress
        self._download_manager = DownloadManager(on_progress=self._handle_download_progress)

    def ensure_native_higgs_registered(self) -> bool:
        """Register the local Q4 native package when its model and DLL are present."""
        model_dir = self._model_store_dir / self.NATIVE_HIGGS_MODEL_ID
        if not model_dir.exists() or not (model_dir / "q4_k_m.gguf").exists():
            return False
        project_root = Path(__file__).resolve().parents[3]
        configured = os.getenv("VOXPASSPORT_HIGGS_NATIVE_DLL", "").strip()
        dll_candidates = [Path(configured)] if configured else []
        dll_candidates.extend([
            project_root / "native" / "audiocpp_engine.dll",
            project_root.parent / "Higgs-Audio-v3-Studio" / "build" / "windows-cuda-release" / "bin" / "audiocpp_engine.dll",
        ])
        dll_path = next((path for path in dll_candidates if path and path.exists()), None)
        if dll_path is None:
            return False
        installed_size_gb = sum(path.stat().st_size for path in model_dir.rglob("*") if path.is_file()) / 1e9
        entry = self.registry.get_entry(self.NATIVE_HIGGS_MODEL_ID)
        if entry is None:
            self.registry.register(ModelRegistryEntry(
                model_id=self.NATIVE_HIGGS_MODEL_ID,
                name="Higgs TTS 3 Q4_K_M (Native CUDA)",
                family="higgs-tts",
                provider="boson-ai / audio.cpp",
                capability=ModelCapability.TTS,
                upstream_id="local://Higgs-Audio-v3-Studio",
                revision="q4_k_m",
                supported_source_languages=["en", "ro", "es", "fr", "de", "it"],
                supported_target_languages=["en", "ro", "es", "fr", "de", "it"],
                supports_english=True,
                supports_romanian=True,
                streaming_support=False,
                voice_cloning_support=True,
                cross_lingual_voice_cloning=True,
                required_runtime="audiocpp_native",
                min_runtime_version="",
                quantization_options=["q4_k_m"],
                estimated_download_size_gb=installed_size_gb,
                installed_size_gb=installed_size_gb,
                expected_vram_tiers={"8GB": "native clone reference capped at 5 seconds"},
                expected_ram_gb=8.0,
                license="See Higgs-Audio-v3-Studio and model terms",
                commercial_use="verify",
                redistribution="verify",
                trust_level="USER_ADDED",
                recommendation_state=RecommendationState.RECOMMENDED_FOR_LOCAL_BENCHMARK,
            ))
            entry = self.registry.get_entry(self.NATIVE_HIGGS_MODEL_ID)
        entry.supported_source_languages = ["en", "ro", "es", "fr", "de", "it"]
        entry.supported_target_languages = ["en", "ro", "es", "fr", "de", "it"]
        entry.supports_english = True
        entry.supports_romanian = True
        entry.voice_cloning_support = True
        entry.cross_lingual_voice_cloning = True
        entry.expected_vram_tiers = {"8GB": "native clone reference capped at 5 seconds"}
        self.registry.register(entry)
        self.registry.update_installation_status(
            self.NATIVE_HIGGS_MODEL_ID,
            InstallationStatus.INSTALLED,
            installed_size_gb=installed_size_gb,
        )
        logger.info("Native Higgs Q4 engine detected: model=%s dll=%s", model_dir, dll_path)
        return True

    def _handle_download_progress(self, task) -> None:
        """Keep persistent registry state synchronized with asynchronous downloads."""
        try:
            if task.phase == "done":
                install_path = self._model_store_dir / task.model_id
                size_gb = None
                if install_path.exists():
                    size_gb = sum(
                        path.stat().st_size for path in install_path.rglob("*") if path.is_file()
                    ) / 1e9
                self.registry.update_installation_status(
                    task.model_id, InstallationStatus.INSTALLED, installed_size_gb=size_gb
                )
            elif task.phase == "failed" and not task.cancelled:
                self.registry.update_installation_status(task.model_id, InstallationStatus.FAILED)
        except Exception:
            logger.warning("Could not synchronize download state for %s", task.model_id, exc_info=True)
        if self._external_on_progress:
            try:
                self._external_on_progress(task)
            except Exception:
                logger.debug("External model progress callback failed", exc_info=True)

    @classmethod
    def canonical_model_id(cls, model_id: str | None) -> str:
        value = str(model_id or "").strip()
        if not value:
            raise ValueError("model_id is required; an active runtime model cannot be empty")
        return cls._ALIASES.get(value.lower(), value)

    @classmethod
    def ui_model_id(cls, model_id: Optional[str]) -> Optional[str]:
        if not model_id:
            return None
        return cls._UI_IDS.get(model_id, model_id)

    @staticmethod
    def normalize_capability(capability: str | None) -> str:
        cap = str(capability or "ASR").strip().upper()
        return "TRANSLATION" if cap in {"NMT", "MT", "TRANSLATE"} else cap

    def list_installed(self) -> List[Dict[str, Any]]:
        return [entry.to_dict() for entry in self.registry.list_entries(installed_only=True)]

    def list_available(self) -> List[Dict[str, Any]]:
        return [entry.to_dict() for entry in self.registry.list_entries()]

    def get_active_slots(self) -> Dict[str, Optional[str]]:
        raw = {slot: getattr(self.registry._active, slot) for slot in KnownGoodModelSet.SLOT_NAMES}
        result: Dict[str, Optional[str]] = dict(raw)
        result["ASR"] = self.ui_model_id(raw.get("asr_en") or raw.get("asr_ro"))
        result["TRANSLATION"] = self.ui_model_id(
            raw.get("translation_en_ro") or raw.get("translation_ro_en")
        )
        result["NMT"] = result["TRANSLATION"]
        result["TTS"] = self.ui_model_id(raw.get("tts_ro") or raw.get("tts_en"))
        result["VAD"] = self.ui_model_id(raw.get("vad"))
        return result

    def _installed_on_disk(self, model_id: str) -> bool:
        return (self._model_store_dir / model_id).exists()

    def _ensure_registry_install_state(self, model_id: str) -> ModelRegistryEntry:
        entry = self.registry.get_entry(model_id)
        if entry is None:
            raise KeyError(f"Unknown model_id: {model_id!r}")
        if entry.installation_status != InstallationStatus.INSTALLED and self._installed_on_disk(model_id):
            self.registry.update_installation_status(model_id, InstallationStatus.INSTALLED)
            entry = self.registry.get_entry(model_id) or entry
        if entry.installation_status != InstallationStatus.INSTALLED:
            raise ValueError(f"Model {model_id!r} is not installed.")
        return entry

    def set_active_model(
        self,
        capability: str,
        model_id: str,
        language: Optional[str] = None,
        language_pair: Optional[str] = None,
    ) -> str:
        cap = self.normalize_capability(capability)
        canonical = self.canonical_model_id(model_id)
        self._ensure_registry_install_state(canonical)

        if cap == "ASR":
            if language:
                self.registry.set_active_model("ASR", canonical, language=language)
            else:
                self.registry.set_active_model("ASR", canonical, language="en")
                self.registry.set_active_model("ASR", canonical, language="ro")
        elif cap == "TTS":
            if language:
                self.registry.set_active_model("TTS", canonical, language=language)
            else:
                self.registry.set_active_model("TTS", canonical, language="en")
                self.registry.set_active_model("TTS", canonical, language="ro")
        elif cap == "TRANSLATION":
            if language_pair:
                self.registry.set_active_model("TRANSLATION", canonical, language_pair=language_pair)
            else:
                self.registry.set_active_model("TRANSLATION", canonical, language_pair="en-ro")
                self.registry.set_active_model("TRANSLATION", canonical, language_pair="ro-en")
        elif cap == "VAD":
            self.registry.set_active_model("VAD", canonical)
        else:
            raise ValueError(
                f"{cap} is catalog/install-only and is not an active serial pipeline slot"
            )
        return canonical

    @staticmethod
    def _infer_capability(model_id: str, upstream_id: str) -> ModelCapability:
        text = f"{model_id} {upstream_id}".lower()
        if any(token in text for token in ("diar", "sortformer", "speaker-diarization")):
            return ModelCapability.DIARIZATION
        if "vad" in text:
            return ModelCapability.VAD
        if any(token in text for token in ("tts", "speech-synthesis", "voice", "omnivoice", "voxcpm", "moss")):
            return ModelCapability.TTS
        if any(token in text for token in ("translate", "translation", "milmmt", "nllb", "madlad")):
            return ModelCapability.TRANSLATION
        return ModelCapability.ASR

    def _register_user_model(self, model_id: str, upstream_id: str, revision: str) -> None:
        capability = self._infer_capability(model_id, upstream_id)
        entry = ModelRegistryEntry(
            model_id=model_id,
            name=upstream_id.split("/")[-1] or model_id,
            family=model_id,
            provider=(upstream_id.split("/")[0] if "/" in upstream_id else "huggingface"),
            capability=capability,
            upstream_id=upstream_id,
            revision=revision or "main",
            supported_source_languages=["*"],
            supported_target_languages=["*"],
            supports_english=True,
            supports_romanian=False,
            streaming_support=False,
            voice_cloning_support=(capability == ModelCapability.TTS),
            cross_lingual_voice_cloning=False,
            required_runtime="transformers",
            min_runtime_version="",
            quantization_options=[],
            estimated_download_size_gb=0.0,
            installed_size_gb=None,
            expected_vram_tiers={},
            expected_ram_gb=None,
            license="verify",
            commercial_use="verify",
            redistribution="verify",
            trust_level="USER_ADDED",
            recommendation_state=RecommendationState.CANDIDATE,
        )
        self.registry.register(entry)

    async def install_model(
        self,
        model_id: str,
        upstream_id: Optional[str] = None,
        revision: Optional[str] = None,
        provider: str = "huggingface",
        expected_checksums: Optional[Dict[str, str]] = None,
    ) -> bool:
        raw_id = str(model_id or "").strip()
        upstream = str(upstream_id or "").strip()
        canonical = self._ALIASES.get(raw_id.lower(), raw_id)
        entry = self.registry.get_entry(canonical)

        if entry is None:
            if not upstream:
                raise ValueError("Unknown models require an upstream_id for installation")
            self._register_user_model(canonical, upstream, revision or "main")
            entry = self.registry.get_entry(canonical)
        if entry is None:
            raise RuntimeError(f"Could not register model {canonical!r}")

        upstream = upstream or entry.upstream_id
        rev = revision or entry.revision or "main"
        if not upstream:
            raise ValueError(
                f"Model {canonical!r} is a watchlist/package-asset entry and has no official Hugging Face repository configured."
            )

        if provider == "local":
            installer = LocalImportInstaller(
                model_store_dir=self._model_store_dir,
                staging_dir=self._staging_dir,
            )
        else:
            installer = HuggingFaceInstaller(
                model_store_dir=self._model_store_dir,
                staging_dir=self._staging_dir,
            )
        self._download_manager.register_installer(canonical, installer)
        self.registry.update_installation_status(canonical, InstallationStatus.DOWNLOADING)
        await self._download_manager.start_install(
            model_id=canonical,
            upstream_id=upstream,
            revision=rev,
            provider=provider,
            expected_checksums=expected_checksums,
        )
        return True

    def cancel_install(self, model_id: str) -> bool:
        canonical = self.canonical_model_id(model_id)
        cancelled = self._download_manager.cancel(canonical)
        if cancelled:
            self.registry.update_installation_status(canonical, InstallationStatus.NOT_INSTALLED)
        return cancelled

    def get_install_progress(self, model_id: str) -> Optional[Dict[str, Any]]:
        canonical = self.canonical_model_id(model_id)
        task = self._download_manager.get_task(canonical)
        if task is None:
            return None
        return {
            "model_id": task.model_id,
            "phase": task.phase,
            "percent": task.percent,
            "bytes_downloaded": task.bytes_downloaded,
            "bytes_total": task.bytes_total,
            "error": task.error,
        }

    def uninstall_model(self, model_id: str) -> bool:
        canonical = self.canonical_model_id(model_id)
        entry = self.registry.get_entry(canonical)
        if not entry:
            return False
        if entry.is_active:
            raise ValueError(f"Cannot uninstall active model {canonical!r}. Switch active model first.")
        if entry.is_pinned:
            raise ValueError(f"Cannot uninstall pinned model {canonical!r}. Unpin it first.")
        install_path = self._model_store_dir / canonical
        if install_path.exists():
            import shutil
            shutil.rmtree(install_path)
        self.registry.update_installation_status(canonical, InstallationStatus.NOT_INSTALLED)
        return True

    def pin_model(self, model_id: str, pinned: bool) -> bool:
        canonical = self.canonical_model_id(model_id)
        entry = self.registry.get_entry(canonical)
        if not entry:
            return False
        entry.is_pinned = bool(pinned)
        self.registry._save()
        return True

    def save_known_good_set(self, version: str = "0.1.0") -> KnownGoodModelSet:
        return self.registry.save_known_good_set(app_version=version)

    def rollback_known_good(self, set_id: Optional[str] = None) -> Optional[KnownGoodModelSet]:
        return self.registry.rollback_to_known_good(set_id=set_id)

    def get_cleanup_candidates(self, n_days_unused: int = 30) -> List[Dict[str, Any]]:
        return [candidate.to_dict() for candidate in self.registry.get_cleanup_candidates(n_days_unused=n_days_unused)]

    def execute_cleanup(self, n_days_unused: int = 30) -> Dict[str, Any]:
        candidates = self.registry.get_cleanup_candidates(n_days_unused=n_days_unused)
        freed_gb = 0.0
        count = 0
        for candidate in candidates:
            try:
                freed_gb += candidate.installed_size_gb or 0.0
                self.uninstall_model(candidate.model_id)
                count += 1
            except Exception as exc:
                logger.warning("Cleanup skipped %s: %s", candidate.model_id, exc)
        return {"count": count, "freed_gb": freed_gb}
