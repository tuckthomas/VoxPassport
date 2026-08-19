"""
VoxPassport — Runtime Inference Daemon Entrypoint
=================================================
Starts the unified local runtime: duplex translation pipelines, caption server,
model manager API, voice-profile studio, and TTS synthesis endpoints.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGES_DIR = PROJECT_ROOT / "packages"
if str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.model_discovery_agent import ModelDiscoveryAgent
from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
from runtime.inference.adapters.tts import (
    HiggsTtsAdapter,
    MossTtsAdapter,
    OmniVoiceTtsAdapter,
    VoxCpmTtsAdapter,
)
from runtime.inference.adapters.vad.silero_vad_adapter import SileroVadAdapter
from runtime.inference.metrics.latency_metrics import PipelineMetrics
from runtime.inference.model_registry.catalog import get_builtin_catalog
from runtime.inference.model_registry.registry import ModelRegistry
from runtime.inference.pipeline.duplex_orchestrator import DuplexOrchestrator
from runtime.inference.pipeline.voice_profile_store import VoiceProfileStore
from runtime.inference.protocol import PipelineMode, TtsMode
from runtime.inference.scheduler.degraded_mode_scheduler import DegradedModeScheduler
from runtime.inference.server.caption_server import CaptionServer
from runtime.inference.server.model_manager_api import ModelManagerController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("VoxPassportDaemon")


class LiveTranslatorApp:
    """Compatibility class name retained while the project finishes the VoxPassport rename."""

    _LANGUAGE_NAMES = {
        "ro": "Romanian",
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
    }

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.registry = ModelRegistry(self.data_dir / "registry.json")
        self.registry.load()
        for entry in get_builtin_catalog():
            if not self.registry.get_entry(entry.model_id):
                self.registry.register(entry)

        self.metrics = PipelineMetrics()
        self.caption_server = CaptionServer(host="127.0.0.1", port=8765)
        self.voice_store = VoiceProfileStore(self.data_dir / "voice_profiles")

        from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import (
            ParakeetTdtV3AsrAdapter,
        )

        self.vad = SileroVadAdapter()
        self.asr_en = ParakeetTdtV3AsrAdapter()
        self.asr_ro = ParakeetTdtV3AsrAdapter()
        self.mt = MiLMMT46TranslationAdapter(model_size="1b")

        # OmniVoice is the in-process engine and remains the initial pipeline TTS
        # adapter. The other engines are independent clients to their own local
        # inference servers; they must never share or masquerade as OmniVoice.
        self.tts_omnivoice = OmniVoiceTtsAdapter()
        self.tts_higgs = HiggsTtsAdapter()
        self.tts_moss = MossTtsAdapter()
        self.tts_voxcpm = VoxCpmTtsAdapter()

        # Compatibility aliases used by the existing duplex orchestrator.
        self.tts_ro = self.tts_omnivoice
        self.tts_en = self.tts_omnivoice

        self.orchestrator = DuplexOrchestrator(
            model_registry=self.registry,
            metrics=self.metrics,
            vad_adapter=self.vad,
            asr_adapter_en=self.asr_en,
            asr_adapter_ro=self.asr_ro,
            mt_adapter=self.mt,
            tts_adapter_ro=self.tts_ro,
            tts_adapter_en=self.tts_en,
            caption_callback=self.caption_server.broadcast_caption,
            mode=PipelineMode.FULL_DUPLEX,
            tts_mode=TtsMode.STOCK,
        )

        self.scheduler = DegradedModeScheduler(
            orchestrator=self.orchestrator,
            metrics=self.metrics,
        )
        self.discovery_agent = ModelDiscoveryAgent(
            registry=self.registry,
            scan_interval_hours=24.0,
        )
        self.model_manager = ModelManagerController(self.registry)
        self._http_runner = None

    @staticmethod
    def _normalize_clone_model(model_name: str | None) -> str:
        model = str(model_name or "omnivoice").strip().lower()
        if any(key in model for key in ("higgs", "boson")):
            return "higgs-tts-3"
        if any(key in model for key in ("moss", "openmoss")):
            return "moss-tts-1.5"
        if any(key in model for key in ("voxcpm", "openbmb")):
            return "voxcpm-2"
        return "omnivoice"

    def _tts_engine_for_model(self, model_name: str | None):
        model = self._normalize_clone_model(model_name)
        if model == "higgs-tts-3":
            return self.tts_higgs, "Higgs TTS 3"
        if model == "moss-tts-1.5":
            return self.tts_moss, "MOSS-TTS v1.5"
        if model == "voxcpm-2":
            return self.tts_voxcpm, "VoxCPM 2"
        return self.tts_omnivoice, "OmniVoice"

    @classmethod
    def _language_name(cls, language_code: str) -> str:
        return cls._LANGUAGE_NAMES.get(str(language_code).lower(), str(language_code))

    async def _setup_http_server(self) -> None:
        from aiohttp import web

        app = web.Application()

        async def api_status(request):
            return web.json_response(
                {
                    "status": "online",
                    "mode": self.orchestrator.mode.value,
                    "tts_mode": self.orchestrator.tts_mode.value,
                    "active_slots": self.model_manager.get_active_slots(),
                }
            )

        async def api_models_available(request):
            return web.json_response(self.model_manager.list_available())

        async def api_models_installed(request):
            return web.json_response(self.model_manager.list_installed())

        async def api_models_active(request):
            data = await request.json()
            capability = data.get("capability", "ASR")
            model_id = data.get("model_id")
            language = data.get("language")
            language_pair = data.get("language_pair")
            self.model_manager.set_active_model(
                capability,
                model_id,
                language=language,
                language_pair=language_pair,
            )
            return web.json_response(
                {"success": True, "active_slots": self.model_manager.get_active_slots()}
            )

        async def api_set_mode(request):
            data = await request.json()
            new_mode = PipelineMode(data.get("mode", "full_duplex"))
            await self.orchestrator.set_mode(new_mode)
            return web.json_response({"success": True, "mode": self.orchestrator.mode.value})

        async def api_set_tts_mode(request):
            data = await request.json()
            new_tts = TtsMode(data.get("tts_mode", "stock"))
            await self.orchestrator.set_tts_mode(new_tts)
            return web.json_response(
                {"success": True, "tts_mode": self.orchestrator.tts_mode.value}
            )

        async def api_translate(request):
            from runtime.inference.protocol import LanguageCode

            data = await request.json()
            text = str(data.get("text", "")).strip()
            source = str(data.get("source", "en")).lower()
            target = str(data.get("target", "ro")).lower()
            if not text:
                return web.json_response({"error": "Empty text"}, status=400)

            def get_lang(code: str) -> LanguageCode:
                try:
                    return LanguageCode(code)
                except ValueError:
                    return LanguageCode.EN

            t0 = asyncio.get_running_loop().time()
            result = await self.mt.translate(
                text,
                source_language=get_lang(source),
                target_language=get_lang(target),
            )
            latency_ms = (asyncio.get_running_loop().time() - t0) * 1000.0
            return web.json_response(
                {
                    "source_text": text,
                    "translated_text": result.translated_text,
                    "source_language": source,
                    "target_language": target,
                    "latency_ms": round(latency_ms, 1),
                }
            )

        def profiles_root() -> Path:
            root = PROJECT_ROOT / "data" / "voice_profiles"
            root.mkdir(parents=True, exist_ok=True)
            return root

        def read_profile_metadata(profile_dir: Path) -> dict:
            import json

            path = profile_dir / "profile.json"
            if not path.exists():
                return {}
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}

        async def api_voice_profiles(request):
            import json

            root = profiles_root()
            active_id = "Default"
            active_file = root / "active_selection.json"
            if active_file.exists():
                try:
                    active_id = json.loads(active_file.read_text()).get("active_id", "Default")
                except Exception:
                    pass

            profiles = []
            for directory in root.iterdir():
                if not directory.is_dir() or directory.name.startswith("."):
                    continue
                meta = read_profile_metadata(directory)
                wav_file = directory / "reference.wav"
                if meta:
                    meta["profile_id"] = directory.name
                    meta["has_audio"] = wav_file.exists()
                    meta["is_active"] = directory.name == active_id
                    profiles.append(meta)
                elif wav_file.exists():
                    profiles.append(
                        {
                            "profile_id": directory.name,
                            "profile_name": directory.name.replace("_", " "),
                            "pitch_hz": 130.0,
                            "clone_model": "omnivoice",
                            "has_audio": True,
                            "is_active": directory.name == active_id,
                        }
                    )
            return web.json_response({"profiles": profiles, "active_id": active_id})

        async def api_voice_rename(request):
            import json

            data = await request.json()
            profile_id = str(data.get("profile_id", "")).strip()
            new_name = str(data.get("new_name", "")).strip()
            if not profile_id or not new_name:
                return web.json_response(
                    {"error": "Missing profile_id or new_name"}, status=400
                )
            profile_dir = profiles_root() / profile_id
            if not profile_dir.exists():
                return web.json_response({"error": "Profile not found"}, status=404)
            meta = read_profile_metadata(profile_dir)
            meta["profile_name"] = new_name
            (profile_dir / "profile.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
            return web.json_response(
                {"success": True, "profile_id": profile_id, "profile_name": new_name}
            )

        async def api_voice_delete(request):
            import shutil

            profile_id = request.match_info.get("profile_id", "")
            if not profile_id:
                return web.json_response({"error": "Missing profile_id"}, status=400)
            profile_dir = profiles_root() / profile_id
            if profile_dir.exists() and profile_dir.is_dir():
                shutil.rmtree(profile_dir, ignore_errors=True)
            return web.json_response({"success": True, "deleted_id": profile_id})

        async def api_voice_activate(request):
            import json

            data = await request.json()
            profile_id = data.get("profile_id", "Default")
            (profiles_root() / "active_selection.json").write_text(
                json.dumps({"active_id": profile_id}), encoding="utf-8"
            )
            return web.json_response({"success": True, "active_id": profile_id})

        async def api_voice_stage(request):
            import json
            import re
            import subprocess

            import numpy as np
            import soundfile as sf

            data = await request.post()
            raw_name = str(data.get("name", "My Voice Profile")).strip() or "My Voice Profile"
            clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name)
            clean_id = re.sub(r"_+", "_", clean_id).strip("_") or "custom_voice"

            staging_dir = profiles_root() / ".staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            wav_path = staging_dir / "reference.wav"
            txt_path = staging_dir / "reference.txt"
            json_path = staging_dir / "profile.json"
            preview_wav_path = staging_dir / "preview_sample.wav"

            transcript_text = str(
                data.get(
                    "transcript",
                    "The quick brown fox jumps over the lazy dog near the riverbank. "
                    "Acoustic speech modeling captures vocal timbre and natural pitch dynamics "
                    "for seamless real-time translation across conferences.",
                )
            ).strip()
            txt_path.write_text(transcript_text, encoding="utf-8")

            audio_file = data.get("audio")
            pitch_hz = 135.0
            if audio_file:
                audio_bytes = audio_file.file.read()
                raw_path = staging_dir / "upload_raw.audio"
                raw_path.write_bytes(audio_bytes)
                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(raw_path),
                            "-ar",
                            "16000",
                            "-ac",
                            "1",
                            "-c:a",
                            "pcm_s16le",
                            str(wav_path),
                        ],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                except Exception as exc:
                    logger.error("FFmpeg staging conversion failed: %s", exc)
                    wav_path.write_bytes(audio_bytes)

                try:
                    audio_data, sample_rate = sf.read(str(wav_path))
                    if audio_data.ndim > 1:
                        audio_data = audio_data.mean(axis=1)
                    length = min(len(audio_data), sample_rate * 2)
                    fft = np.abs(np.fft.rfft(audio_data[:length]))
                    freqs = np.fft.rfftfreq(length, 1.0 / sample_rate)
                    valid = (freqs >= 80) & (freqs <= 300)
                    if np.any(valid):
                        pitch_hz = float(round(freqs[valid][np.argmax(fft[valid])], 1))
                except Exception:
                    pass

            clone_model = self._normalize_clone_model(data.get("clone_model", "omnivoice"))
            profile_info = {
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "clone_model": clone_model,
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "status": "Staged (Pending Save)",
            }
            json_path.write_text(json.dumps(profile_info, indent=2), encoding="utf-8")

            preview_lang = str(data.get("preview_lang", "ro")).lower()
            preview_text = str(
                data.get(
                    "preview_text",
                    "Vântul de primăvară adie lin peste dealurile înverzite ale Carpaților.",
                )
            ).strip()
            if not preview_text:
                preview_text = (
                    "Vântul de primăvară adie lin peste dealurile înverzite ale Carpaților."
                )

            has_preview = False
            engine_name = None
            preview_error = None
            if wav_path.exists():
                tts_engine, engine_name = self._tts_engine_for_model(clone_model)
                try:
                    logger.info(
                        "Synthesizing staged voice preview with %s (%s) for '%s'...",
                        engine_name,
                        self._language_name(preview_lang),
                        raw_name,
                    )
                    audio_res = await asyncio.wait_for(
                        tts_engine.generate_cloned_audio(
                            text=preview_text,
                            ref_audio_path=str(wav_path),
                            ref_text=transcript_text,
                            num_step=32,
                            language=self._language_name(preview_lang),
                        ),
                        timeout=180.0,
                    )
                    if audio_res and len(audio_res) > 500:
                        preview_wav_path.write_bytes(audio_res)
                        has_preview = True
                except Exception as exc:
                    preview_error = str(exc)
                    logger.error(
                        "Staged voice cloning failed with %s: %s", engine_name, exc
                    )

            return web.json_response(
                {
                    "success": True,
                    "profile_id": clean_id,
                    "profile_name": raw_name,
                    "pitch_hz": pitch_hz,
                    "clone_model": clone_model,
                    "engine_name": engine_name,
                    "has_preview": has_preview,
                    "preview_error": preview_error,
                    "preview_url": "/api/voice/staging/preview",
                    "reference_url": "/api/voice/staging/reference",
                }
            )

        async def api_voice_staging_preview(request):
            preview_path = profiles_root() / ".staging" / "preview_sample.wav"
            if preview_path.exists():
                return web.Response(body=preview_path.read_bytes(), content_type="audio/wav")
            return web.Response(status=404, text="No staging preview available")

        async def api_voice_staging_reference(request):
            ref_path = profiles_root() / ".staging" / "reference.wav"
            if ref_path.exists():
                return web.Response(body=ref_path.read_bytes(), content_type="audio/wav")
            return web.Response(status=404, text="No staging reference available")

        async def api_voice_commit_stage(request):
            import json
            import re
            import shutil

            data = await request.json()
            raw_name = str(data.get("name", "")).strip()
            staging_dir = profiles_root() / ".staging"
            if not staging_dir.exists() or not (staging_dir / "reference.wav").exists():
                return web.json_response(
                    {"error": "No staged voice profile found to commit"}, status=400
                )

            pitch_hz = 135.0
            clone_model = "omnivoice"
            staged_meta = read_profile_metadata(staging_dir)
            if staged_meta:
                pitch_hz = staged_meta.get("pitch_hz", 135.0)
                clone_model = self._normalize_clone_model(
                    staged_meta.get("clone_model", "omnivoice")
                )
                if not raw_name:
                    raw_name = staged_meta.get("profile_name", "My Voice Profile")
            if not raw_name:
                raw_name = "My Voice Profile"

            clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name)
            clean_id = re.sub(r"_+", "_", clean_id).strip("_") or "custom_voice"
            target_dir = profiles_root() / clean_id
            target_dir.mkdir(parents=True, exist_ok=True)

            shutil.copy2(staging_dir / "reference.wav", target_dir / "reference.wav")
            if (staging_dir / "reference.txt").exists():
                shutil.copy2(staging_dir / "reference.txt", target_dir / "reference.txt")

            final_info = {
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "clone_model": clone_model,
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "status": "Enrolled & Active",
            }
            (target_dir / "profile.json").write_text(
                json.dumps(final_info, indent=2), encoding="utf-8"
            )
            (profiles_root() / "active_selection.json").write_text(
                json.dumps({"active_id": clean_id}), encoding="utf-8"
            )
            shutil.rmtree(staging_dir, ignore_errors=True)
            return web.json_response(
                {
                    "success": True,
                    "profile_id": clean_id,
                    "profile_name": raw_name,
                    "pitch_hz": pitch_hz,
                    "clone_model": clone_model,
                    "status": "Enrolled & Active",
                }
            )

        async def api_voice_clear_stage(request):
            import shutil

            shutil.rmtree(profiles_root() / ".staging", ignore_errors=True)
            return web.json_response({"success": True})

        async def api_voice_enroll(request):
            """Legacy direct-enrollment endpoint; preserves the selected clone model."""
            import json
            import re
            import subprocess

            import numpy as np
            import soundfile as sf

            data = await request.post()
            raw_name = str(data.get("name", "My Custom Voice")).strip() or "My Custom Voice"
            clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name)
            clean_id = re.sub(r"_+", "_", clean_id).strip("_") or "custom_voice"
            profile_dir = profiles_root() / clean_id
            profile_dir.mkdir(parents=True, exist_ok=True)

            wav_path = profile_dir / "reference.wav"
            txt_path = profile_dir / "reference.txt"
            transcript_text = str(data.get("transcript", "")).strip()
            txt_path.write_text(transcript_text, encoding="utf-8")

            pitch_hz = 135.0
            audio_file = data.get("audio")
            if audio_file:
                audio_bytes = audio_file.file.read()
                raw_path = profile_dir / "upload_raw.audio"
                raw_path.write_bytes(audio_bytes)
                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(raw_path),
                            "-ar",
                            "16000",
                            "-ac",
                            "1",
                            "-c:a",
                            "pcm_s16le",
                            str(wav_path),
                        ],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                except Exception as exc:
                    logger.error("FFmpeg conversion failed: %s", exc)
                    wav_path.write_bytes(audio_bytes)

                try:
                    audio_data, sample_rate = sf.read(str(wav_path))
                    if audio_data.ndim > 1:
                        audio_data = audio_data.mean(axis=1)
                    length = min(len(audio_data), sample_rate * 2)
                    fft = np.abs(np.fft.rfft(audio_data[:length]))
                    freqs = np.fft.rfftfreq(length, 1.0 / sample_rate)
                    valid = (freqs >= 80) & (freqs <= 300)
                    if np.any(valid):
                        pitch_hz = float(round(freqs[valid][np.argmax(fft[valid])], 1))
                except Exception:
                    pass

            clone_model = self._normalize_clone_model(data.get("clone_model", "omnivoice"))
            profile_info = {
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "clone_model": clone_model,
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "status": "Enrolled & Active",
            }
            (profile_dir / "profile.json").write_text(
                json.dumps(profile_info, indent=2), encoding="utf-8"
            )
            (profiles_root() / "active_selection.json").write_text(
                json.dumps({"active_id": clean_id}), encoding="utf-8"
            )
            return web.json_response(
                {
                    "success": True,
                    "profile_id": clean_id,
                    "profile_name": raw_name,
                    "pitch_hz": pitch_hz,
                    "clone_model": clone_model,
                    "saved_file": str(wav_path.relative_to(PROJECT_ROOT)),
                    "status": "Enrolled & Active",
                }
            )

        async def api_voice_audio(request):
            profile_id = request.match_info.get("profile_id", "")
            wav_path = profiles_root() / profile_id / "reference.wav"
            if wav_path.exists():
                return web.Response(body=wav_path.read_bytes(), content_type="audio/wav")
            return web.Response(status=404)

        async def api_synthesize(request):
            """
            Generate cloned speech with the engine selected for the active profile.

            A request-level ``clone_model`` may override the profile for explicit
            A/B tests. There is no silent fallback to OmniVoice or Edge TTS when a
            named cloning backend fails; the caller receives an explicit error.
            """
            import json

            data = await request.json() if request.can_read_body else {}
            raw_text = data.get("text", "Bună ziua, aceasta este vocea mea.")
            if isinstance(raw_text, dict):
                raw_text = raw_text.get("text", "")
            text = str(raw_text).strip()
            if not text:
                return web.json_response({"error": "Empty synthesis text"}, status=400)
            target_lang = str(data.get("target", "ro")).lower()

            root = profiles_root()
            profile_id = data.get("profile_id")
            if not profile_id:
                active_file = root / "active_selection.json"
                if active_file.exists():
                    try:
                        profile_id = json.loads(active_file.read_text()).get("active_id")
                    except Exception:
                        pass
            if not profile_id:
                for directory in root.iterdir():
                    if directory.is_dir() and not directory.name.startswith(".") and (
                        directory / "reference.wav"
                    ).exists():
                        profile_id = directory.name
                        break
            if not profile_id:
                return web.json_response(
                    {"error": "No enrolled voice profile is available"}, status=404
                )

            profile_dir = root / str(profile_id)
            wav_path = profile_dir / "reference.wav"
            if not wav_path.exists():
                return web.json_response(
                    {"error": f"Voice profile {profile_id!r} has no reference audio"},
                    status=404,
                )

            ref_text = ""
            text_path = profile_dir / "reference.txt"
            if text_path.exists():
                try:
                    ref_text = text_path.read_text(encoding="utf-8").strip()
                except Exception:
                    pass

            profile_meta = read_profile_metadata(profile_dir)
            request_override = str(data.get("clone_model", "")).strip()
            clone_model = self._normalize_clone_model(
                request_override or profile_meta.get("clone_model", "omnivoice")
            )
            tts_engine, engine_name = self._tts_engine_for_model(clone_model)
            target_language_name = self._language_name(target_lang)

            logger.info(
                "Cloning speech with %s (%s) for profile '%s'...",
                engine_name,
                target_language_name,
                profile_id,
            )
            try:
                audio_bytes = await asyncio.wait_for(
                    tts_engine.generate_cloned_audio(
                        text=text,
                        ref_audio_path=str(wav_path),
                        ref_text=ref_text,
                        num_step=32,
                        language=target_language_name,
                    ),
                    timeout=180.0,
                )
            except Exception as exc:
                logger.exception("%s cloning failed: %s", engine_name, exc)
                return web.json_response(
                    {
                        "error": "TTS backend failed",
                        "engine": engine_name,
                        "clone_model": clone_model,
                        "detail": str(exc),
                    },
                    status=502,
                )

            if not audio_bytes or len(audio_bytes) <= 500:
                return web.json_response(
                    {
                        "error": "TTS backend returned no usable audio",
                        "engine": engine_name,
                        "clone_model": clone_model,
                    },
                    status=502,
                )

            return web.Response(
                body=audio_bytes,
                content_type="audio/wav",
                headers={
                    "X-VoxPassport-TTS-Engine": engine_name,
                    "X-VoxPassport-Clone-Model": clone_model,
                },
            )

        async def api_verify(request):
            """ASR/back-translation diagnostic for generated audio."""
            import io
            import re
            import urllib.parse

            import requests
            import speech_recognition as sr
            from pydub import AudioSegment

            try:
                reader = await request.multipart()
                audio_bytes = None
                orig_text = ""
                src_lang = "en"
                tgt_lang = "ro"
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == "audio":
                        audio_bytes = await part.read()
                    elif part.name == "original_text":
                        orig_text = (await part.text()).strip()
                    elif part.name == "source_lang":
                        src_lang = (await part.text()).strip().lower()
                    elif part.name == "target_lang":
                        tgt_lang = (await part.text()).strip().lower()

                if not audio_bytes:
                    return web.json_response(
                        {"error": "No audio payload provided for verification"}, status=400
                    )

                seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
                wav_io = io.BytesIO()
                seg.export(wav_io, format="wav")
                wav_io.seek(0)

                asr_locale_map = {
                    "ro": "ro-RO",
                    "es": "es-ES",
                    "fr": "fr-FR",
                    "de": "de-DE",
                    "it": "it-IT",
                    "en": "en-US",
                }
                recognizer = sr.Recognizer()
                with sr.AudioFile(wav_io) as source:
                    rec_audio = recognizer.record(source)
                try:
                    asr_transcript = recognizer.recognize_google(
                        rec_audio,
                        language=asr_locale_map.get(tgt_lang, "ro-RO"),
                    )
                except sr.UnknownValueError:
                    return web.json_response(
                        {
                            "success": False,
                            "error": "ASR could not recognize speech from audio",
                            "asr_transcript": "[Unintelligible Audio]",
                            "back_translated_text": "[Unintelligible Audio]",
                            "similarity_pct": 0,
                            "match_type": "NO MATCH (ASR FAILED)",
                        }
                    )

                url = (
                    "https://translate.googleapis.com/translate_a/single"
                    f"?client=gtx&sl={tgt_lang}&tl={src_lang}&dt=t"
                    f"&q={urllib.parse.quote(asr_transcript)}"
                )
                resp = requests.get(url, timeout=5)
                back_translated = asr_transcript
                if resp.ok:
                    payload = resp.json()
                    back_translated = "".join(
                        chunk[0] for chunk in payload[0] if chunk and chunk[0]
                    )

                def normalize_tokens(value: str) -> list[str]:
                    return re.findall(r"\w+", value.lower())

                orig_tokens = normalize_tokens(orig_text)
                back_tokens = normalize_tokens(back_translated)
                if not orig_tokens:
                    similarity_pct = 100 if not back_tokens else 0
                else:
                    matches = sum(
                        1 for token in back_tokens if token in set(orig_tokens)
                    )
                    similarity_pct = round(
                        matches / max(len(orig_tokens), len(back_tokens)) * 100.0, 1
                    )
                match_type = (
                    "100% MATCH"
                    if similarity_pct >= 95
                    else ("SEMANTIC MATCH" if similarity_pct >= 50 else "PARTIAL / LOW MATCH")
                )
                return web.json_response(
                    {
                        "success": True,
                        "asr_transcript": asr_transcript,
                        "back_translated_text": back_translated,
                        "similarity_pct": similarity_pct,
                        "match_type": match_type,
                    }
                )
            except Exception as exc:
                logger.exception("Accuracy verification error: %s", exc)
                return web.json_response(
                    {"error": f"Verification error: {exc}"}, status=500
                )

        app.router.add_get("/api/status", api_status)
        app.router.add_get("/api/models/available", api_models_available)
        app.router.add_get("/api/models/installed", api_models_installed)
        app.router.add_post("/api/models/active", api_models_active)
        app.router.add_post("/api/mode", api_set_mode)
        app.router.add_post("/api/tts-mode", api_set_tts_mode)
        app.router.add_post("/api/translate", api_translate)
        app.router.add_get("/api/voice/profiles", api_voice_profiles)
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
                return web.HTTPFound("/manager/index.html")

            app.router.add_get("/", index_redirect)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 8766)
        await site.start()
        self._http_runner = runner
        logger.info("VoxPassport Web UI & API ready at http://127.0.0.1:8766")

    async def start(self) -> None:
        logger.info("Initializing VoxPassport Daemon...")
        await self.caption_server.start()
        await self._setup_http_server()
        await self.orchestrator.start()
        await self.scheduler.start()
        await self.discovery_agent.start()
        logger.info("VoxPassport Daemon is FULLY ONLINE.")

    async def stop(self) -> None:
        logger.info("Shutting down VoxPassport Daemon...")
        if self._http_runner:
            await self._http_runner.cleanup()
        await self.discovery_agent.stop()
        await self.scheduler.stop()
        await self.orchestrator.stop()
        await self.caption_server.stop()
        logger.info("Shutdown complete.")


async def main():
    parser = argparse.ArgumentParser(description="VoxPassport Runtime Daemon")
    parser.add_argument("--data-dir", default="data", help="Directory for models and profiles")
    args = parser.parse_args()

    app = LiveTranslatorApp(data_dir=Path(args.data_dir))
    await app.start()
    try:
        while True:
            await asyncio.sleep(1.0)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
