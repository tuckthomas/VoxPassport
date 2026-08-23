"""VoxPassport unified local runtime daemon."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGES_DIR = PROJECT_ROOT / "packages"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PACKAGES_DIR) not in sys.path:
    sys.path.append(str(PACKAGES_DIR))

from runtime.inference.model_discovery_agent import ModelDiscoveryAgent
from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import ParakeetTdtV3AsrAdapter
from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
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
from runtime.inference.server.resource_monitor import ResourceSnapshotCollector
from runtime.inference.tts_plugins import TtsManifestCatalog, manifest_registry_entry
from runtime.inference.remote_runtime import (
    RemoteAsrAdapter, RemoteEndpoint, RemoteEndpointStore, RemoteTranslationAdapter,
    RemoteTtsAdapter, remote_model_id,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("VoxPassportDaemon")


class LiveTranslatorApp:
    """Unified VoxPassport runtime and control plane."""

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
        self._model_settings_path = self.data_dir / "model_settings.json"
        self._model_store_dir = self._load_model_store_dir()

        self.registry = ModelRegistry(self.data_dir / "registry.json")
        self.registry.load()
        # TTS metadata is manifest-owned. The general catalog continues to own
        # ASR, translation, VAD, diarization, and direct-speech candidates.
        for entry in get_builtin_catalog():
            if entry.capability == ModelCapability.TTS:
                continue
            if not self.registry.get_entry(entry.model_id):
                self.registry.register(entry)

        self.tts_manifest_catalog = TtsManifestCatalog().load()
        for manifest in self.tts_manifest_catalog.manifests():
            existing = self.registry.get_entry(manifest.model_id)
            self.registry.register(manifest_registry_entry(manifest, existing))
        self._manifest_tts_adapters: dict[str, ManifestTtsAdapter] = {}

        self.metrics = PipelineMetrics()
        self.caption_server = CaptionServer(host="127.0.0.1", port=8765)
        self.voice_store = VoiceProfileStore(self.profiles_dir)

        self.vad = SileroVadAdapter()
        self.asr_en = ParakeetTdtV3AsrAdapter()
        self.asr_ro = ParakeetTdtV3AsrAdapter()
        self.mt = MiLMMT46TranslationAdapter(model_size="1b")

        default_tts_manifest = self.tts_manifest_catalog.resolve("omnivoice-stock")
        default_tts = ManifestTtsAdapter(
            default_tts_manifest,
            profiles_root=self.profiles_dir,
            catalog=self.tts_manifest_catalog,
        )
        self._manifest_tts_adapters[default_tts_manifest.model_id] = default_tts
        self._selected_tts_model = default_tts_manifest.model_id

        self.orchestrator = DuplexOrchestrator(
            model_registry=self.registry,
            metrics=self.metrics,
            vad_adapter=self.vad,
            asr_adapter_en=self.asr_en,
            asr_adapter_ro=self.asr_ro,
            mt_adapter=self.mt,
            tts_adapter_ro=default_tts,
            tts_adapter_en=default_tts,
            caption_callback=self.caption_server.broadcast_caption,
            mode=PipelineMode.CAPTIONS_ONLY,
            tts_mode=TtsMode.STOCK,
            user_language=LanguageCode.EN,
            remote_language=LanguageCode.RO,
        )
        self.scheduler = DegradedModeScheduler(orchestrator=self.orchestrator, metrics=self.metrics)
        self.discovery_agent = ModelDiscoveryAgent(registry=self.registry, scan_interval_hours=24.0)
        self.model_manager = ModelManagerController(
            self.registry,
            model_store_dir=self._model_store_dir,
            staging_dir=self._model_store_dir / ".staging",
        )
        for manifest in self.tts_manifest_catalog.manifests():
            for alias in (manifest.model_id, *manifest.aliases):
                self.model_manager._ALIASES[str(alias).strip().lower()] = manifest.model_id

        self.remote_endpoints = RemoteEndpointStore(self.data_dir / "remote_endpoints.json")
        self._register_remote_endpoints()
        self.resource_monitor = ResourceSnapshotCollector()
        self._resource_ws_clients: set[object] = set()
        self._resource_stream_task: asyncio.Task | None = None
        self._http_runner = None
        self._runtime_settings_path = PROJECT_ROOT / "data" / "runtime_settings.json"
        self._runtime_residency = self._load_runtime_residency()
        self._runtime_idle_task: asyncio.Task | None = None
        self._runtime_activity_lock = asyncio.Lock()
        self._runtime_last_activity = 0.0

    def _load_model_store_dir(self) -> Path:
        try:
            configured = json.loads(self._model_settings_path.read_text(encoding="utf-8")).get("model_store_dir")
            if configured:
                return Path(str(configured)).expanduser().resolve()
        except Exception:
            pass
        return PROJECT_ROOT / "models"

    def _save_model_store_dir(self, location: str) -> str:
        candidate = Path(location).expanduser().resolve()
        candidate.mkdir(parents=True, exist_ok=True)
        self._model_store_dir = candidate
        self.model_manager._model_store_dir = candidate
        self.model_manager._staging_dir = candidate / ".staging"
        self._model_settings_path.write_text(json.dumps({"model_store_dir": str(candidate)}, indent=2), encoding="utf-8")
        return str(candidate)

    def _register_remote_endpoints(self) -> None:
        """Expose configured remote capabilities as normal installed model entries."""
        for endpoint in self.remote_endpoints.list():
            for capability_name in endpoint.capabilities:
                model_id = remote_model_id(endpoint.endpoint_id, capability_name)
                if self.registry.get_entry(model_id):
                    continue
                capability = ModelCapability.TRANSLATION if capability_name == "TRANSLATION" else ModelCapability(capability_name)
                self.registry.register(ModelRegistryEntry(
                    model_id=model_id, name=f"{endpoint.name} · {endpoint.selected_model_id or capability_name} (cloud)",
                    family="remote-worker", provider="remote", capability=capability,
                    upstream_id=endpoint.base_url, revision="remote", supported_source_languages=["*"],
                    supported_target_languages=["*"], supports_english=True, supports_romanian=True,
                    streaming_support=capability_name in {"TTS", "ASR"}, voice_cloning_support=capability_name == "TTS",
                    cross_lingual_voice_cloning=capability_name == "TTS", required_runtime="remote_worker",
                    min_runtime_version="v1", quantization_options=[], estimated_download_size_gb=0,
                    installed_size_gb=0, expected_vram_tiers={}, expected_ram_gb=None, license="configured by operator",
                    commercial_use="verify", redistribution="verify", trust_level="USER_ADDED",
                    recommendation_state=RecommendationState.CANDIDATE,
                    installation_status=InstallationStatus.INSTALLED, eligible_for_cleanup=False,
                ))

    def _remote_endpoint_for_model(self, model_id: str, capability: str) -> RemoteEndpoint | None:
        parts = str(model_id).split("::")
        if len(parts) != 3 or parts[0] != "remote" or parts[2] != capability:
            return None
        return self.remote_endpoints.get(parts[1])

    def _load_runtime_residency(self) -> str:
        try:
            data = json.loads(self._runtime_settings_path.read_text(encoding="utf-8"))
            value = str(data.get("model_residency", "ready")).strip().lower()
            return value if value in {"ready", "on_demand"} else "ready"
        except Exception:
            return "ready"

    def _save_runtime_residency(self) -> None:
        self._runtime_settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._runtime_settings_path.write_text(
            json.dumps({"model_residency": self._runtime_residency}, indent=2),
            encoding="utf-8",
        )

    def _touch_runtime_activity(self) -> None:
        self._runtime_last_activity = time.monotonic()

    async def _ensure_runtime_ready(self) -> None:
        self._touch_runtime_activity()
        if self.orchestrator._is_active:
            return
        async with self._runtime_activity_lock:
            if not self.orchestrator._is_active:
                await self.orchestrator.start()
            self._touch_runtime_activity()
        if self._runtime_residency == "on_demand":
            self._schedule_runtime_idle_release()

    def _schedule_runtime_idle_release(self) -> None:
        if self._runtime_idle_task and not self._runtime_idle_task.done():
            self._runtime_idle_task.cancel()
        self._runtime_idle_task = asyncio.create_task(self._release_runtime_when_idle())

    async def _release_runtime_when_idle(self) -> None:
        try:
            await asyncio.sleep(30.0)
            if (
                self._runtime_residency == "on_demand"
                and self.orchestrator._is_active
                and time.monotonic() - self._runtime_last_activity >= 30.0
            ):
                await self.orchestrator.stop()
                logger.info("On Demand mode released idle inference models")
        except asyncio.CancelledError:
            return

    async def _set_runtime_residency(self, value: str) -> None:
        value = str(value).strip().lower()
        if value not in {"ready", "on_demand"}:
            raise ValueError("model_residency must be 'ready' or 'on_demand'")
        self._runtime_residency = value
        self._save_runtime_residency()
        if value == "ready":
            await self._ensure_runtime_ready()
        else:
            if self._runtime_idle_task and not self._runtime_idle_task.done():
                self._runtime_idle_task.cancel()
            if self.orchestrator._is_active:
                await self.orchestrator.stop()
            logger.info("On Demand mode released inference models")

    def _normalize_clone_model(self, model_name: str | None) -> str:
        raw = str(model_name or "omnivoice-stock").strip()
        if raw.startswith("remote::"):
            return raw
        manifest = self.tts_manifest_catalog.resolve_optional(raw)
        if manifest is not None:
            return manifest.model_id
        canonical = self.model_manager.canonical_model_id(raw)
        manifest = self.tts_manifest_catalog.resolve_optional(canonical)
        if manifest is not None:
            return manifest.model_id
        raise ValueError(f"No local TTS manifest registered for {raw!r}")

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
        canonical = self._normalize_clone_model(model_name)
        if canonical.startswith("remote::"):
            endpoint = self._remote_endpoint_for_model(canonical, "TTS")
            if endpoint is None:
                raise ValueError(f"Unknown remote TTS endpoint for {canonical!r}")
            return RemoteTtsAdapter(endpoint), endpoint.name
        manifest = self.tts_manifest_catalog.resolve(canonical)
        adapter = self._manifest_tts_adapters.get(manifest.model_id)
        if adapter is None:
            adapter = ManifestTtsAdapter(
                manifest,
                profiles_root=self.profiles_dir,
                catalog=self.tts_manifest_catalog,
            )
            self._manifest_tts_adapters[manifest.model_id] = adapter
        return adapter, manifest.display_name

    def _active_tts_model(self) -> str:
        selected = self.model_manager.get_active_slots().get("TTS") or self._selected_tts_model
        return self._normalize_clone_model(selected)

    async def _mark_default_runtime_models(self) -> None:
        defaults = [
            ("nvidia-parakeet-tdt-0.6b-v3", "ASR"),
            ("xiaomi-milmmt-46-1b-v1.0", "TRANSLATION"),
            ("omnivoice-stock", "TTS"),
            ("silero-vad-v4", "VAD"),
        ]
        active_keys = {"ASR": "ASR", "TRANSLATION": "NMT", "TTS": "TTS", "VAD": "VAD"}
        for model_id, capability in defaults:
            if not self.registry.get_entry(model_id):
                continue
            try:
                self.registry.update_installation_status(model_id, InstallationStatus.INSTALLED)
                if self.model_manager.get_active_slots().get(active_keys[capability]):
                    continue
                self.model_manager.set_active_model(capability, model_id)
            except Exception as exc:
                logger.warning("Could not bootstrap active %s model %s: %s", capability, model_id, exc)

    def _profile_metadata(self, profile_dir: Path) -> dict:
        path = profile_dir / "profile.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

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
            remote = self._remote_endpoint_for_model(canonical, cap)
            if remote:
                if cap == "ASR":
                    adapter_en, adapter_ro = RemoteAsrAdapter(remote), RemoteAsrAdapter(remote)
                    await adapter_en.load(); await adapter_ro.load()
                    healthy = await adapter_en.health_check()
                    if healthy:
                        await self.orchestrator.set_asr_adapters(adapter_en, adapter_ro)
                        self.asr_en, self.asr_ro = adapter_en, adapter_ro
                elif cap == "TRANSLATION":
                    adapter = RemoteTranslationAdapter(remote)
                    await adapter.load()
                    healthy = await adapter.health_check()
                    if healthy:
                        await self.orchestrator.set_translation_adapter(adapter)
                        self.mt = adapter
                elif cap == "TTS":
                    adapter = RemoteTtsAdapter(remote)
                    await adapter.load()
                    healthy = await adapter.health_check()
                    if healthy:
                        await self.orchestrator.set_tts_adapter(adapter)
                        self._selected_tts_model = canonical
                else:
                    raise ValueError("Remote VAD is intentionally not supported; it must remain local for realtime capture")
                if not healthy:
                    raise RuntimeError(f"Remote endpoint {remote.name!r} is not reachable")
                return self.model_manager.set_active_model(cap, canonical)

            if cap == "TTS":
                canonical = self._normalize_clone_model(canonical)
                engine, _ = self._tts_engine_for_model(canonical)
                await engine.load()
                if not await engine.health_check():
                    raise RuntimeError(f"{canonical} TTS plugin is not healthy after load")
                if self.registry.get_entry(canonical):
                    self.registry.update_installation_status(canonical, InstallationStatus.INSTALLED)
                canonical = self.model_manager.set_active_model("TTS", canonical)
                await self.orchestrator.set_tts_adapter(engine)
                self._selected_tts_model = canonical
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
            slots["TTS"] = self.model_manager.ui_model_id(self._active_tts_model())
            return web.json_response({
                "status": "online",
                "mode": self.orchestrator.mode.value,
                "tts_mode": self.orchestrator.tts_mode.value,
                "user_language": self.orchestrator.user_language.value,
                "remote_language": self.orchestrator.remote_language.value,
                "active_slots": slots,
                "model_residency": self._runtime_residency,
                "models_loaded": self.orchestrator._is_active,
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

        async def api_model_pipeline(request):
            data = await request.json()
            try:
                success = self.model_manager.set_pipeline_enabled(
                    str(data.get("model_id", "")), bool(data.get("enabled", False))
                )
                return web.json_response({"success": success})
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_model_storage(request):
            if request.method == "GET":
                return web.json_response({"model_store_dir": str(self._model_store_dir)})
            try:
                data = await request.json()
                path = self._save_model_store_dir(str(data.get("model_store_dir", "")))
                return web.json_response({"success": True, "model_store_dir": path})
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_remote_endpoints(request):
            if request.method == "GET":
                return web.json_response([{
                    "endpoint_id": x.endpoint_id, "name": x.name, "base_url": x.base_url,
                    "capabilities": x.capabilities, "auth_token_env": x.auth_token_env, "selected_model_id": x.selected_model_id,
                } for x in self.remote_endpoints.list()])
            data = await request.json()
            try:
                endpoint = self.remote_endpoints.upsert(
                    name=str(data.get("name", "")), base_url=str(data.get("base_url", "")),
                    capabilities=data.get("capabilities", []), auth_token_env=str(data.get("auth_token_env", "")),
                    endpoint_id=str(data.get("endpoint_id", "")), selected_model_id=str(data.get("selected_model_id", "")),
                )
                self._register_remote_endpoints()
                return web.json_response({"success": True, "endpoint_id": endpoint.endpoint_id})
            except Exception as exc:
                return web.json_response({"success": False, "error": str(exc)}, status=400)

        async def api_remote_endpoint_delete(request):
            endpoint_id = request.match_info["endpoint_id"]
            active = set(filter(None, self.model_manager.get_active_slots().values()))
            if any(remote_model_id(endpoint_id, cap) in active for cap in ("ASR", "TRANSLATION", "TTS")):
                return web.json_response({"success": False, "error": "Switch active cloud slots before removing this endpoint"}, status=409)
            return web.json_response({"success": self.remote_endpoints.delete(endpoint_id)})

        async def api_resources(request):
            snapshot = await asyncio.to_thread(self.resource_monitor.snapshot)
            return web.json_response(snapshot)

        async def resource_stream_loop():
            try:
                while self._resource_ws_clients:
                    snapshot = await asyncio.to_thread(self.resource_monitor.snapshot)
                    stale = []
                    for websocket in list(self._resource_ws_clients):
                        if websocket.closed:
                            stale.append(websocket)
                            continue
                        try:
                            await websocket.send_json({"type": "resources", "data": snapshot})
                        except Exception:
                            stale.append(websocket)
                    for websocket in stale:
                        self._resource_ws_clients.discard(websocket)
                    if self._resource_ws_clients:
                        await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                raise
            finally:
                if self._resource_stream_task is asyncio.current_task():
                    self._resource_stream_task = None

        async def ws_resources(request):
            websocket = web.WebSocketResponse(heartbeat=30)
            await websocket.prepare(request)
            self._resource_ws_clients.add(websocket)
            if self._resource_stream_task is None or self._resource_stream_task.done():
                self._resource_stream_task = asyncio.create_task(resource_stream_loop())
            try:
                async for message in websocket:
                    if message.type in (web.WSMsgType.CLOSE, web.WSMsgType.ERROR):
                        break
            finally:
                self._resource_ws_clients.discard(websocket)
                if not self._resource_ws_clients and self._resource_stream_task:
                    self._resource_stream_task.cancel()
            return websocket

        async def api_models_progress(request):
            model_id = request.query.get("model_id", "").strip()
            if not model_id:
                return web.json_response({"error": "model_id required"}, status=400)
            prog = self.model_manager.get_install_progress(model_id)
            if prog is None:
                try:
                    canonical = self.model_manager.canonical_model_id(model_id)
                    entry = self.model_manager.registry.get_entry(canonical)
                    if entry and entry.installation_status == InstallationStatus.INSTALLED:
                        return web.json_response({"model_id": model_id, "phase": "done", "percent": 100.0})
                except Exception:
                    pass
                return web.json_response({"model_id": model_id, "phase": "idle", "percent": 0.0})
            return web.json_response(prog)

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

        async def api_runtime_residency(request):
            if request.method == "GET":
                return web.json_response({
                    "model_residency": self._runtime_residency,
                    "models_loaded": self.orchestrator._is_active,
                })
            data = await request.json()
            try:
                await self._set_runtime_residency(data.get("model_residency", "ready"))
                return web.json_response({
                    "success": True,
                    "model_residency": self._runtime_residency,
                    "models_loaded": self.orchestrator._is_active,
                })
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
                await self._ensure_runtime_ready()
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
                        "status": "Reference profile",
                    }
                meta["profile_id"] = directory.name
                meta["has_audio"] = wav.exists()
                translated_audio = directory / "translated_sample.wav"
                meta["has_translation_audio"] = translated_audio.exists()
                if translated_audio.exists():
                    meta["translation_url"] = f"/api/voice/translation/{directory.name}"
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
            manifest = self.tts_manifest_catalog.resolve_optional(preview_model)
            if manifest is not None and manifest.transcript_required and not transcript:
                return web.json_response({
                    "success": False,
                    "error": f"{manifest.display_name} requires the exact reference transcript for voice cloning",
                    "preview_model": preview_model,
                }, status=422)
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
                "preview_lang": preview_lang,
                "preview_text": preview_text,
                "translation_audio": "translated_sample.wav",
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
            if (staging / "preview_sample.wav").exists():
                shutil.copy2(staging / "preview_sample.wav", target / "translated_sample.wav")
                meta["translation_audio"] = "translated_sample.wav"
                meta["has_translation_audio"] = True
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

        async def api_voice_translation(request):
            path = self.profiles_dir / request.match_info.get("profile_id", "") / "translated_sample.wav"
            return web.Response(body=path.read_bytes(), content_type="audio/wav") if path.exists() else web.Response(status=404)

        def save_profile_translation_sample(directory: Path, audio: bytes, model: str, target: str, text: str) -> None:
            (directory / "translated_sample.wav").write_bytes(audio)
            meta = self._profile_metadata(directory)
            meta.update({
                "translation_audio": "translated_sample.wav",
                "has_translation_audio": True,
                "last_preview_model": model,
                "preview_lang": target,
                "preview_text": text,
            })
            (directory / "profile.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

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
            await self._ensure_runtime_ready()

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
            manifest = self.tts_manifest_catalog.resolve_optional(selected_model)
            engine, engine_name = self._tts_engine_for_model(selected_model)
            if manifest is not None and manifest.transcript_required and not ref_text:
                return web.json_response({
                    "error": f"{manifest.display_name} requires the exact reference transcript for voice cloning",
                    "engine": engine_name,
                }, status=422)
            preview_cache_path = None
            if bool(data.get("preview", False)):
                cache_material = json.dumps({
                    "version": 4,
                    "model": selected_model,
                    "target": target,
                    "text": text,
                    "reference_size": wav.stat().st_size,
                    "reference_mtime_ns": wav.stat().st_mtime_ns,
                    "reference_text": ref_text,
                }, ensure_ascii=False, sort_keys=True).encode("utf-8")
                cache_key = hashlib.sha256(cache_material).hexdigest()[:24]
                preview_cache_dir = directory / ".preview_cache"
                preview_cache_dir.mkdir(parents=True, exist_ok=True)
                preview_cache_path = preview_cache_dir / f"{cache_key}.wav"
                if preview_cache_path.exists() and preview_cache_path.stat().st_size > 500:
                    cached_audio = preview_cache_path.read_bytes()
                    save_profile_translation_sample(directory, cached_audio, selected_model, target, text)
                    return web.Response(
                        body=cached_audio,
                        content_type="audio/wav",
                        headers={
                            "X-VoxPassport-TTS-Engine": engine_name,
                            "X-VoxPassport-Clone-Model": selected_model,
                            "X-VoxPassport-Preview-Cache": "HIT",
                        },
                    )
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
                if preview_cache_path is not None:
                    preview_cache_path.write_bytes(audio)
                    save_profile_translation_sample(directory, audio, selected_model, target, text)
                return web.Response(
                    body=audio,
                    content_type="audio/wav",
                    headers={
                        "X-VoxPassport-TTS-Engine": engine_name,
                        "X-VoxPassport-Clone-Model": selected_model,
                        "X-VoxPassport-Preview-Cache": "MISS" if preview_cache_path else "BYPASS",
                    },
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
                await self._ensure_runtime_ready()
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
        app.router.add_get("/api/resources", api_resources)
        app.router.add_get("/ws/resources", ws_resources)
        app.router.add_get("/api/models/available", api_models_available)
        app.router.add_get("/api/models/installed", api_models_installed)
        app.router.add_get("/api/models/progress", api_models_progress)
        app.router.add_post("/api/models/active", api_models_active)
        app.router.add_post("/api/models/pipeline", api_model_pipeline)
        app.router.add_route("*", "/api/settings/model-storage", api_model_storage)
        app.router.add_route("*", "/api/remote-endpoints", api_remote_endpoints)
        app.router.add_delete("/api/remote-endpoints/{endpoint_id}", api_remote_endpoint_delete)
        app.router.add_post("/api/models/install", api_models_install)
        app.router.add_post("/api/models/uninstall", api_models_uninstall)
        app.router.add_post("/api/models/discover", api_models_discover)
        app.router.add_post("/api/mode", api_set_mode)
        app.router.add_route("*", "/api/runtime/residency", api_runtime_residency)
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
        app.router.add_get("/api/voice/translation/{profile_id}", api_voice_translation)
        app.router.add_post("/api/synthesize", api_synthesize)
        app.router.add_post("/api/verify", api_verify)

        companion_dir = PROJECT_ROOT / "apps" / "desktop-companion"
        assets_dir = companion_dir / "assets"
        manager_dir = companion_dir / "model-manager"
        overlay_dir = companion_dir / "overlay"
        if assets_dir.exists():
            app.router.add_static("/assets", path=str(assets_dir), show_index=False)
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
        saved_tts = self.model_manager.get_active_slots().get("TTS") or self._selected_tts_model
        persisted_tts = self._normalize_clone_model(saved_tts)
        persisted_tts_engine = self._tts_engine_for_model(persisted_tts)[0]
        self.orchestrator.tts_adapter_ro = persisted_tts_engine
        self.orchestrator.tts_adapter_en = persisted_tts_engine
        self._selected_tts_model = persisted_tts
        active_slots = self.model_manager.get_active_slots()
        persisted_asr = active_slots.get("ASR")
        remote_asr = self._remote_endpoint_for_model(persisted_asr, "ASR") if persisted_asr else None
        if remote_asr:
            self.asr_en, self.asr_ro = RemoteAsrAdapter(remote_asr), RemoteAsrAdapter(remote_asr)
            self.orchestrator.asr_adapter_en, self.orchestrator.asr_adapter_ro = self.asr_en, self.asr_ro
        persisted_translation = active_slots.get("TRANSLATION")
        remote_translation = self._remote_endpoint_for_model(persisted_translation, "TRANSLATION") if persisted_translation else None
        if remote_translation:
            self.mt = RemoteTranslationAdapter(remote_translation)
            self.orchestrator.mt_adapter = self.mt
        logger.info("Restored persisted TTS engine before pipeline startup: %s", persisted_tts)
        await self.caption_server.start()
        await self._setup_http_server()
        if self._runtime_residency == "ready":
            await self.orchestrator.start()
        else:
            logger.info("On Demand model residency enabled; deferring inference model loading")
        await self._mark_default_runtime_models()
        await self.scheduler.start()
        await self.discovery_agent.start()
        logger.info("VoxPassport daemon is online")

    async def stop(self) -> None:
        if self._resource_stream_task:
            self._resource_stream_task.cancel()
            self._resource_stream_task = None
        for websocket in list(self._resource_ws_clients):
            try:
                await websocket.close()
            except Exception:
                pass
        self._resource_ws_clients.clear()
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
