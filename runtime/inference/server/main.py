"""VoxPassport unified local runtime daemon."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGES_DIR = PROJECT_ROOT / "packages"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PACKAGES_DIR) not in sys.path:
    sys.path.append(str(PACKAGES_DIR))

from agents.model_discovery_agent import ModelDiscoveryAgent
from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import ParakeetTdtV3AsrAdapter
from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
from runtime.inference.adapters.tts import HiggsTtsAdapter, MossTtsAdapter, OmniVoiceTtsAdapter, VoxCpmTtsAdapter
from runtime.inference.adapters.vad.silero_vad_adapter import SileroVadAdapter
from runtime.inference.metrics.latency_metrics import PipelineMetrics
from runtime.inference.model_registry.catalog import get_builtin_catalog
from runtime.inference.model_registry.registry import ModelRegistry, ModelRegistryEntry
from runtime.inference.pipeline.duplex_orchestrator import DuplexOrchestrator
from runtime.inference.pipeline.voice_profile_store import VoiceProfileStore
from runtime.inference.protocol import (
    InstallationStatus,
    LanguageCode,
    ModelCapability,
    PipelineMode,
    RecommendationState,
    TtsMode,
)
from runtime.inference.scheduler.degraded_mode_scheduler import DegradedModeScheduler
from runtime.inference.server.caption_server import CaptionServer
from runtime.inference.server.model_manager_api import ModelManagerController

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("VoxPassportDaemon")


class LiveTranslatorApp:
    """Compatibility class name retained while the remaining source files are renamed."""

    _LANGUAGE_NAMES = {
        "en": "English", "ro": "Romanian", "es": "Spanish", "fr": "French",
        "de": "German", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
        "pl": "Polish", "cs": "Czech", "hu": "Hungarian", "tr": "Turkish",
        "ru": "Russian", "uk": "Ukrainian", "bg": "Bulgarian", "el": "Greek",
        "ar": "Arabic", "he": "Hebrew", "hi": "Hindi", "ja": "Japanese",
        "ko": "Korean", "zh": "Chinese (Simplified)",
    }

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir = self.data_dir / "voice_profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        self.registry = ModelRegistry(self.data_dir / "registry.json")
        self.registry.load()
        for entry in get_builtin_catalog():
            if not self.registry.get_entry(entry.model_id):
                self.registry.register(entry)

        self.metrics = PipelineMetrics()
        self.caption_server = CaptionServer(host="127.0.0.1", port=8765)
        self.voice_store = VoiceProfileStore(self.profiles_dir)

        self.vad = SileroVadAdapter()
        self.asr_en = ParakeetTdtV3AsrAdapter()
        self.asr_ro = ParakeetTdtV3AsrAdapter()
        self.mt = MiLMMT46TranslationAdapter(model_size="1b")

        self.tts_omnivoice = OmniVoiceTtsAdapter()
        self.tts_omnivoice._profiles_root = self.profiles_dir
        self.tts_higgs = HiggsTtsAdapter(profiles_root=self.profiles_dir)
        self.tts_moss = MossTtsAdapter(profiles_root=self.profiles_dir)
        self.tts_voxcpm = VoxCpmTtsAdapter()
        self._selected_tts_model = "omnivoice"

        self.orchestrator = DuplexOrchestrator(
            model_registry=self.registry,
            metrics=self.metrics,
            vad_adapter=self.vad,
            asr_adapter_en=self.asr_en,
            asr_adapter_ro=self.asr_ro,
            mt_adapter=self.mt,
            tts_adapter_ro=self.tts_omnivoice,
            tts_adapter_en=self.tts_omnivoice,
            caption_callback=self.caption_server.broadcast_caption,
            mode=PipelineMode.FULL_DUPLEX,
            tts_mode=TtsMode.STOCK,
            user_language=LanguageCode.EN,
            remote_language=LanguageCode.RO,
        )
        self.scheduler = DegradedModeScheduler(orchestrator=self.orchestrator, metrics=self.metrics)
        self.discovery_agent = ModelDiscoveryAgent(registry=self.registry, scan_interval_hours=24.0)
        self.model_manager = ModelManagerController(
            self.registry,
            model_store_dir=PROJECT_ROOT / "models",
            staging_dir=PROJECT_ROOT / "models" / ".staging",
        )
        self._http_runner = None

    @staticmethod
    def _normalize_clone_model(model_name: str | None) -> str:
        model = str(model_name or "omnivoice").strip().lower()
        if any(k in model for k in ("higgs", "boson")):
            return "higgs-tts-3"
        if any(k in model for k in ("moss", "openmoss")):
            return "moss-tts-1.5"
        if any(k in model for k in ("voxcpm", "openbmb")):
            return "voxcpm-2"
        return "omnivoice"

    @classmethod
    def _language_name(cls, language_code: str) -> str:
        return cls._LANGUAGE_NAMES.get(str(language_code).lower(), str(language_code))

    @staticmethod
    def _language_code(value: str) -> LanguageCode:
        try:
            return LanguageCode(str(value).lower())
        except ValueError as exc:
            raise ValueError(f"Unsupported runtime language code: {value!r}") from exc

    def _tts_engine_for_model(self, model_name: str | None):
        model = self._normalize_clone_model(model_name)
        if model == "higgs-tts-3":
            return self.tts_higgs, "Higgs TTS 3"
        if model == "moss-tts-1.5":
            return self.tts_moss, "MOSS-TTS v1.5"
        if model == "voxcpm-2":
            return self.tts_voxcpm, "VoxCPM 2"
        return self.tts_omnivoice, "OmniVoice"

    def _active_tts_model(self) -> str:
        active = self.model_manager.get_active_slots().get("TTS")
        return self._normalize_clone_model(active or self._selected_tts_model)

    def _register_external_tts_if_needed(self, canonical: str) -> None:
        if self.registry.get_entry(canonical):
            return
        names = {
            "moss-tts-1.5": ("MOSS-TTS v1.5", "openmoss", "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"),
            "voxcpm-2": ("VoxCPM 2", "openbmb", "openbmb/VoxCPM2"),
        }
        if canonical not in names:
            return
        name, provider, upstream = names[canonical]
        self.registry.register(
            ModelRegistryEntry(
                model_id=canonical,
                name=name,
                family=canonical,
                provider=provider,
                capability=ModelCapability.TTS,
                upstream_id=upstream,
                revision="main",
                supported_source_languages=[],
                supported_target_languages=["*"],
                supports_english=True,
                supports_romanian=True,
                streaming_support=True,
                voice_cloning_support=True,
                cross_lingual_voice_cloning=True,
                required_runtime="local_worker",
                min_runtime_version="",
                quantization_options=[],
                estimated_download_size_gb=0.0,
                installed_size_gb=None,
                expected_vram_tiers={},
                expected_ram_gb=None,
                license="verify",
                commercial_use="verify",
                redistribution="verify",
                trust_level="OFFICIAL_VERIFIED",
                recommendation_state=RecommendationState.CANDIDATE,
            )
        )

    async def _mark_default_runtime_models(self) -> None:
        defaults = [
            ("nvidia-parakeet-tdt-0.6b-v3", "ASR"),
            ("xiaomi-milmmt-46-1b-v1.0", "TRANSLATION"),
            ("omnivoice-stock", "TTS"),
            ("silero-vad-v4", "VAD"),
        ]
        for model_id, capability in defaults:
            if not self.registry.get_entry(model_id):
                continue
            try:
                self.registry.update_installation_status(model_id, InstallationStatus.INSTALLED)
                self.model_manager.set_active_model(capability, model_id)
            except Exception as exc:
                logger.warning("Could not bootstrap active %s model %s: %s", capability, model_id, exc)

    def _profile_metadata(self, profile_dir: Path) -> dict:
        path = profile_dir / "profile.json"
        if not path.exists():
            return {}
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        # Migrate old model-bound profiles to universal reference profiles.
        if "clone_model" in meta:
            meta.setdefault("last_preview_model", self._normalize_clone_model(meta.pop("clone_model")))
            try:
                path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            except Exception:
                pass
        return meta

    @staticmethod
    def _safe_profile_id(name: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        return re.sub(r"_+", "_", clean).strip("_") or "custom_voice"

    @staticmethod
    def _convert_upload_to_wav(audio_file, wav_path: Path) -> None:
        raw_path = wav_path.with_name("upload_raw.audio")
        raw_path.write_bytes(audio_file.file.read())
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(raw_path), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            raise RuntimeError(f"FFmpeg could not normalize reference audio: {exc}") from exc
        finally:
            try:
                raw_path.unlink()
            except Exception:
                pass

    @staticmethod
    def _estimate_pitch(wav_path: Path) -> float:
        try:
            import numpy as np
            import soundfile as sf
            audio, sr = sf.read(str(wav_path), dtype="float32")
            if getattr(audio, "ndim", 1) > 1:
                audio = audio.mean(axis=1)
            length = min(len(audio), int(sr * 2))
            if length <= 0:
                return 135.0
            fft = np.abs(np.fft.rfft(audio[:length]))
            freqs = np.fft.rfftfreq(length, 1.0 / sr)
            valid = (freqs >= 70) & (freqs <= 350)
            if np.any(valid):
                return float(round(freqs[valid][np.argmax(fft[valid])], 1))
        except Exception:
            pass
        return 135.0

    async def _activate_runtime_model(self, capability: str, requested_model: str) -> str:
        cap = self.model_manager.normalize_capability(capability)
        canonical = self.model_manager.canonical_model_id(requested_model)
        previous = self.model_manager.get_active_slots().get(cap if cap != "TRANSLATION" else "NMT")

        try:
            if cap == "TTS":
                normalized = self._normalize_clone_model(canonical)
                engine, _ = self._tts_engine_for_model(normalized)
                await engine.load()
                if normalized == "omnivoice":
                    await self.tts_omnivoice._ensure_omnivoice_loaded()
                    canonical = "omnivoice-stock"
                else:
                    healthy = await engine.health_check() if hasattr(engine, "health_check") else True
                    if not healthy:
                        raise RuntimeError(f"{normalized} backend is not reachable")
                    canonical = normalized
                    self._register_external_tts_if_needed(canonical)
                if self.registry.get_entry(canonical):
                    self.registry.update_installation_status(canonical, InstallationStatus.INSTALLED)
                canonical = self.model_manager.set_active_model("TTS", canonical)
                await self.orchestrator.set_tts_adapter(engine)
                self._selected_tts_model = self._normalize_clone_model(canonical)
                return canonical

            if cap == "TRANSLATION":
                if "milmmt" not in canonical.lower():
                    raise ValueError("Downloaded model has no implemented VoxPassport translation adapter yet")
                adapter = MiLMMT46TranslationAdapter(model_size="4b" if "4b" in canonical.lower() else "1b")
                await adapter.load()
                if self.registry.get_entry(canonical):
                    self.registry.update_installation_status(canonical, InstallationStatus.INSTALLED)
                canonical = self.model_manager.set_active_model("TRANSLATION", canonical)
                await self.orchestrator.set_translation_adapter(adapter)
                self.mt = adapter
                return canonical

            if cap == "ASR":
                if "parakeet" not in canonical.lower():
                    raise ValueError("Downloaded model has no implemented production streaming ASR adapter yet")
                adapter_en = ParakeetTdtV3AsrAdapter()
                adapter_ro = ParakeetTdtV3AsrAdapter()
                await adapter_en.load()
                await adapter_ro.load()
                if self.registry.get_entry(canonical):
                    self.registry.update_installation_status(canonical, InstallationStatus.INSTALLED)
                canonical = self.model_manager.set_active_model("ASR", canonical)
                await self.orchestrator.set_asr_adapters(adapter_en, adapter_ro)
                self.asr_en, self.asr_ro = adapter_en, adapter_ro
                return canonical

            if cap == "VAD":
                if "silero" not in canonical.lower():
                    raise ValueError("Downloaded model has no implemented VoxPassport VAD adapter yet")
                adapter = SileroVadAdapter()
                await adapter.load()
                if self.registry.get_entry(canonical):
                    self.registry.update_installation_status(canonical, InstallationStatus.INSTALLED)
                canonical = self.model_manager.set_active_model("VAD", canonical)
                await self.orchestrator.set_vad_adapter(adapter)
                self.vad = adapter
                return canonical

            raise ValueError(f"Unsupported capability: {cap}")
        except Exception:
            # Persisted state is changed only after a candidate loads, but restore
            # a prior registry selection if a later pipeline rebind fails.
            if previous:
                try:
                    self.model_manager.set_active_model(cap, previous)
                except Exception:
                    pass
            raise

    async def _setup_http_server(self) -> None:
        from aiohttp import web

        app = web.Application(client_max_size=200 * 1024 * 1024)

        async def api_status(request):
            slots = self.model_manager.get_active_slots()
            slots["TTS"] = self.model_manager.ui_model_id(
                self.model_manager.canonical_model_id(self._active_tts_model())
                if self._active_tts_model() == "omnivoice" else self._active_tts_model()
            )
            return web.json_response({
                "status": "online",
                "mode": self.orchestrator.mode.value,
                "tts_mode": self.orchestrator.tts_mode.value,
                "user_language": self.orchestrator.user_language.value,
                "remote_language": self.orchestrator.remote_language.value,
                "active_slots": slots,
            })

        async def api_models_available(request):
            return web.json_response(self.model_manager.list_available())

        async def api_models_installed(request):
            return web.json_response(self.model_manager.list_installed())

        async def api_models_active(request):
            data = await request.json()
            model_id = str(data.get("model_id", "")).strip()
            capability = str(data.get("capability", "ASR"))
            if not model_id:
                return web.json_response({"success": False, "error": "model_id cannot be empty"}, status=400)
            try:
                canonical = await self._activate_runtime_model(capability, model_id)
                return web.json_response({
                    "success": True,
                    "model_id": canonical,
                    "ui_model_id": self.model_manager.ui_model_id(canonical),
                    "active_slots": self.model_manager.get_active_slots(),
                })
            except Exception as exc:
                logger.exception("Model activation failed: %s / %s", capability, model_id)
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_hardware_profile(request):
            import platform
            import psutil
            import torch

            cuda = torch.cuda.is_available()
            gpu_name = torch.cuda.get_device_name(0) if cuda else "CPU Only"
            total_vram = 0.0
            free_vram = 0.0
            if cuda:
                try:
                    free_bytes, total_bytes = torch.cuda.mem_get_info(0)
                    total_vram = round(total_bytes / 1024**3, 2)
                    free_vram = round(free_bytes / 1024**3, 2)
                except Exception:
                    total_vram = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2)
                    free_vram = round(max(0.0, total_vram - torch.cuda.memory_reserved(0) / 1024**3), 2)

            cpu_name = platform.processor() or "CPU"
            if sys.platform == "win32":
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                        cpu_name = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
                except Exception:
                    pass
            total_ram = round(psutil.virtual_memory().total / 1024**3, 2)
            tier = "high" if total_vram >= 15.5 else ("balanced" if total_vram >= 7.5 else "low")
            return web.json_response({
                "cuda_available": cuda,
                "gpu_name": gpu_name,
                "total_vram_gb": total_vram,
                "available_vram_gb": free_vram,
                "cpu_name": cpu_name,
                "cpu_cores": psutil.cpu_count(logical=True) or 1,
                "cpu_physical_cores": psutil.cpu_count(logical=False) or 1,
                "total_ram_gb": total_ram,
                "tier": tier,
                "max_recommended_slot_vram_gb": 3.5 if tier == "balanced" else (8.0 if tier == "high" else 1.5),
            })

        async def api_models_install(request):
            data = await request.json()
            try:
                ok = await self.model_manager.install_model(
                    model_id=data.get("model_id"),
                    upstream_id=data.get("upstream_id"),
                    revision=data.get("revision"),
                )
                return web.json_response({"success": ok, "model_id": data.get("model_id")})
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_models_uninstall(request):
            data = await request.json()
            try:
                return web.json_response({
                    "success": self.model_manager.uninstall_model(data.get("model_id")),
                    "model_id": data.get("model_id"),
                })
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_models_discover(request):
            try:
                candidates = await self.discovery_agent.run_discovery_pass()
                return web.json_response({"success": True, "count": len(candidates), "models": self.model_manager.list_available()})
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=500)

        async def api_set_mode(request):
            data = await request.json()
            try:
                mode = PipelineMode(data.get("mode", "full_duplex"))
                await self.orchestrator.set_mode(mode)
                return web.json_response({"success": True, "mode": mode.value})
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_set_tts_mode(request):
            data = await request.json()
            raw = str(data.get("tts_mode", "tts_no_clone"))
            if raw in {"cloned", "clone", "tts_cloned"}:
                raw = TtsMode.CLONED.value
            elif raw in {"stock", "tts_no_clone"}:
                raw = TtsMode.STOCK.value
            try:
                mode = TtsMode(raw)
                await self.orchestrator.set_tts_mode(mode)
                return web.json_response({"success": True, "tts_mode": mode.value})
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_languages(request):
            if request.method == "GET":
                return web.json_response({
                    "user_language": self.orchestrator.user_language.value,
                    "remote_language": self.orchestrator.remote_language.value,
                    "supported": [x.value for x in LanguageCode],
                })
            data = await request.json()
            try:
                user_lang = self._language_code(data.get("user_language", self.orchestrator.user_language.value))
                remote_lang = self._language_code(data.get("remote_language", self.orchestrator.remote_language.value))
                await self.orchestrator.set_language_pair(user_lang, remote_lang)
                return web.json_response({"success": True, "user_language": user_lang.value, "remote_language": remote_lang.value})
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_translate(request):
            data = await request.json()
            text = str(data.get("text", "")).strip()
            if not text:
                return web.json_response({"error": "Empty text"}, status=400)
            try:
                src = self._language_code(data.get("source", "en"))
                tgt = self._language_code(data.get("target", "ro"))
                result = await self.orchestrator.mt_adapter.translate(text, source_language=src, target_language=tgt)
                return web.json_response({
                    "source_text": text,
                    "translated_text": result.translated_text,
                    "source_language": src.value,
                    "target_language": tgt.value,
                    "latency_ms": round(result.latency_ms, 1),
                })
            except Exception as exc:
                logger.exception("Translation failed")
                return web.json_response({"error": str(exc)}, status=502)

        async def api_voice_profiles(request):
            active_id = ""
            active_file = self.profiles_dir / "active_selection.json"
            if active_file.exists():
                try:
                    active_id = str(json.loads(active_file.read_text(encoding="utf-8")).get("active_id", ""))
                except Exception:
                    pass
            profiles = []
            for directory in self.profiles_dir.iterdir():
                if not directory.is_dir() or directory.name.startswith("."):
                    continue
                wav = directory / "reference.wav"
                meta = self._profile_metadata(directory)
                if not meta and not wav.exists():
                    continue
                if not meta:
                    meta = {
                        "profile_id": directory.name,
                        "profile_name": directory.name.replace("_", " "),
                        "pitch_hz": 130.0,
                        "status": "Legacy profile",
                    }
                meta["profile_id"] = directory.name
                meta["has_audio"] = wav.exists()
                meta["is_active"] = directory.name == active_id
                profiles.append(meta)
            return web.json_response({"profiles": profiles, "active_id": active_id})

        async def api_voice_rename(request):
            data = await request.json()
            profile_id = str(data.get("profile_id", "")).strip()
            new_name = str(data.get("new_name", "")).strip()
            if not profile_id or not new_name:
                return web.json_response({"error": "Missing profile_id or new_name"}, status=400)
            directory = self.profiles_dir / profile_id
            if not directory.exists():
                return web.json_response({"error": "Profile not found"}, status=404)
            meta = self._profile_metadata(directory)
            meta["profile_name"] = new_name
            (directory / "profile.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return web.json_response({"success": True, "profile_id": profile_id, "profile_name": new_name})

        async def api_voice_delete(request):
            profile_id = request.match_info.get("profile_id", "")
            directory = self.profiles_dir / profile_id
            if directory.exists() and directory.is_dir():
                shutil.rmtree(directory, ignore_errors=True)
            active_file = self.profiles_dir / "active_selection.json"
            if active_file.exists():
                try:
                    active = json.loads(active_file.read_text(encoding="utf-8")).get("active_id", "")
                    if active == profile_id:
                        active_file.write_text(json.dumps({"active_id": ""}), encoding="utf-8")
                except Exception:
                    pass
            return web.json_response({"success": True, "deleted_id": profile_id})

        async def api_voice_activate(request):
            data = await request.json()
            profile_id = str(data.get("profile_id", "")).strip()
            if profile_id and not (self.profiles_dir / profile_id / "reference.wav").exists():
                return web.json_response({"error": "Profile not found or has no reference audio"}, status=404)
            (self.profiles_dir / "active_selection.json").write_text(json.dumps({"active_id": profile_id}), encoding="utf-8")
            return web.json_response({"success": True, "active_id": profile_id})

        async def api_voice_stage(request):
            data = await request.post()
            raw_name = str(data.get("name", "My Voice Profile")).strip() or "My Voice Profile"
            profile_id = self._safe_profile_id(raw_name)
            staging = self.profiles_dir / ".staging"
            staging.mkdir(parents=True, exist_ok=True)
            wav_path = staging / "reference.wav"
            txt_path = staging / "reference.txt"
            preview_path = staging / "preview_sample.wav"

            transcript = str(data.get("transcript", "")).strip()
            txt_path.write_text(transcript, encoding="utf-8")
            audio_file = data.get("audio")
            if not audio_file:
                return web.json_response({"success": False, "error": "No reference audio supplied"}, status=400)
            try:
                self._convert_upload_to_wav(audio_file, wav_path)
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

            preview_lang = str(data.get("preview_lang", "ro")).lower()
            preview_text = str(data.get("preview_text", "Vântul de primăvară adie lin peste dealurile înverzite ale Carpaților.")).strip()
            preview_model = self._normalize_clone_model(data.get("clone_model") or self._active_tts_model())
            engine, engine_name = self._tts_engine_for_model(preview_model)
            meta = {
                "profile_id": profile_id,
                "profile_name": raw_name,
                "pitch_hz": self._estimate_pitch(wav_path),
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "ref_lang": str(data.get("ref_lang", "en")).lower(),
                "status": "Staged (Pending Save)",
                "last_preview_model": preview_model,
            }
            (staging / "profile.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            if preview_path.exists():
                preview_path.unlink()

            try:
                await engine.load()
                audio = await asyncio.wait_for(
                    engine.generate_cloned_audio(
                        text=preview_text,
                        ref_audio_path=str(wav_path),
                        ref_text=transcript,
                        num_step=32,
                        language=self._language_name(preview_lang),
                    ),
                    timeout=240,
                )
                if not audio or len(audio) <= 500:
                    raise RuntimeError("TTS backend returned no usable preview audio")
                preview_path.write_bytes(audio)
                return web.json_response({
                    "success": True,
                    "profile_id": profile_id,
                    "profile_name": raw_name,
                    "pitch_hz": meta["pitch_hz"],
                    "preview_model": preview_model,
                    "engine_name": engine_name,
                    "has_preview": True,
                    "preview_url": "/api/voice/staging/preview",
                    "reference_url": "/api/voice/staging/reference",
                })
            except Exception as exc:
                logger.exception("Staged preview failed with %s", engine_name)
                return web.json_response({
                    "success": False,
                    "profile_id": profile_id,
                    "profile_name": raw_name,
                    "preview_model": preview_model,
                    "engine_name": engine_name,
                    "has_preview": False,
                    "preview_error": str(exc),
                    "reference_url": "/api/voice/staging/reference",
                })

        async def api_voice_staging_preview(request):
            path = self.profiles_dir / ".staging" / "preview_sample.wav"
            return web.Response(body=path.read_bytes(), content_type="audio/wav") if path.exists() else web.Response(status=404)

        async def api_voice_staging_reference(request):
            path = self.profiles_dir / ".staging" / "reference.wav"
            return web.Response(body=path.read_bytes(), content_type="audio/wav") if path.exists() else web.Response(status=404)

        async def api_voice_commit_stage(request):
            data = await request.json()
            staging = self.profiles_dir / ".staging"
            if not (staging / "reference.wav").exists():
                return web.json_response({"error": "No staged voice profile found to commit"}, status=400)
            meta = self._profile_metadata(staging)
            raw_name = str(data.get("name") or meta.get("profile_name") or "My Voice Profile").strip()
            profile_id = self._safe_profile_id(raw_name)
            target = self.profiles_dir / profile_id
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / "reference.wav", target / "reference.wav")
            if (staging / "reference.txt").exists():
                shutil.copy2(staging / "reference.txt", target / "reference.txt")
            meta.update({
                "profile_id": profile_id,
                "profile_name": raw_name,
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "status": "Enrolled & Active",
            })
            meta.pop("clone_model", None)
            (target / "profile.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            (self.profiles_dir / "active_selection.json").write_text(json.dumps({"active_id": profile_id}), encoding="utf-8")
            shutil.rmtree(staging, ignore_errors=True)
            return web.json_response({"success": True, **meta})

        async def api_voice_clear_stage(request):
            shutil.rmtree(self.profiles_dir / ".staging", ignore_errors=True)
            return web.json_response({"success": True})

        async def api_voice_enroll(request):
            data = await request.post()
            raw_name = str(data.get("name", "My Voice Profile")).strip() or "My Voice Profile"
            transcript = str(data.get("transcript", "")).strip()
            if not transcript:
                return web.json_response({
                    "success": False,
                    "error": "A transcript of uploaded reference audio is required for an engine-agnostic voice profile. Use Voice Profile Studio or supply transcript.",
                }, status=400)
            audio_file = data.get("audio")
            if not audio_file:
                return web.json_response({"success": False, "error": "No reference audio supplied"}, status=400)
            profile_id = self._safe_profile_id(raw_name)
            directory = self.profiles_dir / profile_id
            directory.mkdir(parents=True, exist_ok=True)
            wav = directory / "reference.wav"
            try:
                self._convert_upload_to_wav(audio_file, wav)
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)
            (directory / "reference.txt").write_text(transcript, encoding="utf-8")
            meta = {
                "profile_id": profile_id,
                "profile_name": raw_name,
                "pitch_hz": self._estimate_pitch(wav),
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "ref_lang": str(data.get("ref_lang", "en")).lower(),
                "status": "Enrolled & Active",
            }
            (directory / "profile.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            (self.profiles_dir / "active_selection.json").write_text(json.dumps({"active_id": profile_id}), encoding="utf-8")
            return web.json_response({"success": True, **meta})

        async def api_voice_audio(request):
            path = self.profiles_dir / request.match_info.get("profile_id", "") / "reference.wav"
            return web.Response(body=path.read_bytes(), content_type="audio/wav") if path.exists() else web.Response(status=404)

        async def api_synthesize(request):
            data = await request.json() if request.can_read_body else {}
            text = str(data.get("text", "")).strip()
            if not text:
                return web.json_response({"error": "Empty synthesis text"}, status=400)
            target = str(data.get("target", self.orchestrator.remote_language.value)).lower()
            try:
                self._language_code(target)
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)

            profile_id = str(data.get("profile_id", "")).strip()
            if not profile_id:
                active_file = self.profiles_dir / "active_selection.json"
                if active_file.exists():
                    try:
                        profile_id = str(json.loads(active_file.read_text(encoding="utf-8")).get("active_id", ""))
                    except Exception:
                        pass
            if not profile_id:
                return web.json_response({"error": "No active voice profile"}, status=404)
            directory = self.profiles_dir / profile_id
            wav = directory / "reference.wav"
            if not wav.exists():
                return web.json_response({"error": f"Voice profile {profile_id!r} has no reference audio"}, status=404)
            ref_text_path = directory / "reference.txt"
            ref_text = ref_text_path.read_text(encoding="utf-8").strip() if ref_text_path.exists() else ""

            selected_model = self._normalize_clone_model(data.get("clone_model") or self._active_tts_model())
            engine, engine_name = self._tts_engine_for_model(selected_model)
            if not ref_text and selected_model != "omnivoice":
                return web.json_response({
                    "error": "This reference profile has no transcript; the selected TTS backend requires one",
                    "engine": engine_name,
                }, status=422)
            try:
                await engine.load()
                audio = await asyncio.wait_for(
                    engine.generate_cloned_audio(
                        text=text,
                        ref_audio_path=str(wav),
                        ref_text=ref_text,
                        num_step=32,
                        language=self._language_name(target),
                    ),
                    timeout=240,
                )
                if not audio or len(audio) <= 500:
                    raise RuntimeError("TTS backend returned no usable audio")
                return web.Response(
                    body=audio,
                    content_type="audio/wav",
                    headers={"X-VoxPassport-TTS-Engine": engine_name, "X-VoxPassport-Clone-Model": selected_model},
                )
            except Exception as exc:
                logger.exception("%s synthesis failed", engine_name)
                return web.json_response({
                    "error": "TTS backend failed", "engine": engine_name,
                    "clone_model": selected_model, "detail": str(exc),
                }, status=502)

        async def api_verify(request):
            import numpy as np
            import soundfile as sf
            from scipy.signal import resample_poly

            try:
                reader = await request.multipart()
                audio_bytes = None
                original = ""
                src = "en"
                tgt = "ro"
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == "audio":
                        audio_bytes = await part.read()
                    elif part.name == "original_text":
                        original = (await part.text()).strip()
                    elif part.name == "source_lang":
                        src = (await part.text()).strip().lower()
                    elif part.name == "target_lang":
                        tgt = (await part.text()).strip().lower()
                if not audio_bytes:
                    return web.json_response({"error": "No audio payload provided"}, status=400)

                audio, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
                if getattr(audio, "ndim", 1) > 1:
                    audio = audio.mean(axis=1)
                if int(sr) != 16000:
                    import math
                    factor = math.gcd(int(sr), 16000)
                    audio = resample_poly(audio, 16000 // factor, int(sr) // factor)
                pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
                await self.asr_en.load()
                transcript = await asyncio.get_running_loop().run_in_executor(None, self.asr_en._transcribe_blocking, pcm, 16000)
                back = await self.orchestrator.mt_adapter.translate(
                    transcript,
                    source_language=self._language_code(tgt),
                    target_language=self._language_code(src),
                )
                back_text = back.translated_text
                orig_tokens = re.findall(r"\w+", original.lower())
                back_tokens = re.findall(r"\w+", back_text.lower())
                if not orig_tokens:
                    similarity = 100.0 if not back_tokens else 0.0
                else:
                    orig_set = set(orig_tokens)
                    matches = sum(1 for token in back_tokens if token in orig_set)
                    similarity = round(matches / max(len(orig_tokens), len(back_tokens), 1) * 100.0, 1)
                match_type = "100% MATCH" if similarity >= 95 else ("SEMANTIC MATCH" if similarity >= 50 else "PARTIAL / LOW MATCH")
                return web.json_response({
                    "success": True,
                    "asr_transcript": transcript,
                    "back_translated_text": back_text,
                    "similarity_pct": similarity,
                    "match_type": match_type,
                })
            except Exception as exc:
                logger.exception("Local verification failed")
                return web.json_response({"error": f"Verification error: {exc}"}, status=500)

        app.router.add_get("/api/status", api_status)
        app.router.add_get("/api/hardware/profile", api_hardware_profile)
        app.router.add_get("/api/models/available", api_models_available)
        app.router.add_get("/api/models/installed", api_models_installed)
        app.router.add_post("/api/models/active", api_models_active)
        app.router.add_post("/api/models/install", api_models_install)
        app.router.add_post("/api/models/uninstall", api_models_uninstall)
        app.router.add_post("/api/models/discover", api_models_discover)
        app.router.add_post("/api/mode", api_set_mode)
        app.router.add_post("/api/tts-mode", api_set_tts_mode)
        app.router.add_get("/api/languages", api_languages)
        app.router.add_post("/api/languages", api_languages)
        app.router.add_post("/api/translate", api_translate)
        app.router.add_get("/api/voice/profiles", api_voice_profiles)
        app.router.add_post("/api/voice/rename", api_voice_rename)
        app.router.add_post("/api/voice/activate", api_voice_activate)
        app.router.add_post("/api/voice/stage", api_voice_stage)
        app.router.add_get("/api/voice/staging/preview", api_voice_staging_preview)
        app.router.add_get("/api/voice/staging/reference", api_voice_staging_reference)
        app.router.add_post("/api/voice/commit_stage", api_voice_commit_stage)
        app.router.add_post("/api/voice/clear_stage", api_voice_clear_stage)
        app.router.add_post("/api/voice/enroll", api_voice_enroll)
        app.router.add_delete("/api/voice/profiles/{profile_id}", api_voice_delete)
        app.router.add_get("/api/voice/audio/{profile_id}", api_voice_audio)
        app.router.add_post("/api/synthesize", api_synthesize)
        app.router.add_post("/api/verify", api_verify)

        companion_dir = PROJECT_ROOT / "apps" / "desktop-companion"
        manager_dir = companion_dir / "model-manager"
        overlay_dir = companion_dir / "overlay"
        if manager_dir.exists():
            app.router.add_static("/manager", path=str(manager_dir), show_index=True)
        if overlay_dir.exists():
            app.router.add_static("/overlay", path=str(overlay_dir), show_index=True)

        async def index_redirect(request):
            raise web.HTTPFound("/manager/index.html")
        app.router.add_get("/", index_redirect)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 8766)
        await site.start()
        self._http_runner = runner
        logger.info("VoxPassport UI/API ready at http://127.0.0.1:8766")

    async def start(self) -> None:
        logger.info("Initializing VoxPassport daemon")
        await self.caption_server.start()
        await self.orchestrator.start()
        await self._mark_default_runtime_models()
        await self._setup_http_server()
        await self.scheduler.start()
        await self.discovery_agent.start()
        logger.info("VoxPassport daemon is online")

    async def stop(self) -> None:
        if self._http_runner:
            await self._http_runner.cleanup()
        await self.discovery_agent.stop()
        await self.scheduler.stop()
        await self.orchestrator.stop()
        await self.caption_server.stop()


async def main() -> None:
    parser = argparse.ArgumentParser(description="VoxPassport Runtime Daemon")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    app = LiveTranslatorApp(Path(args.data_dir))
    await app.start()
    try:
        while True:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
