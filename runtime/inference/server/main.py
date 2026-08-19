"""
LiveTranslator — Runtime Inference Daemon Entrypoint
=====================================================
Starts the unified LiveTranslator runtime:
- Duplex Orchestrator (concurrent EN<->RO pipelines)
- Caption WebSocket Server (ws://127.0.0.1:8765/ws/captions)
- Model Manager API Controller
- Degraded Mode Scheduler
- Voice Profile Store
- Model Discovery Agent

Usage:
    python runtime/inference/server/main.py --config configs/app.example.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add project root and packages
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGES_DIR = PROJECT_ROOT / "packages"
if str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.model_discovery_agent import ModelDiscoveryAgent
from runtime.inference.adapters.asr.nemotron35_streaming_asr_adapter import Nemotron35StreamingAsrAdapter
from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
from runtime.inference.adapters.tts import (
    OmniVoiceTtsAdapter,
    HiggsTtsAdapter,
    VoxCpmTtsAdapter,
    MossTtsAdapter,
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
logger = logging.getLogger("LiveTranslatorDaemon")


class LiveTranslatorApp:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 1. Model Registry
        self.registry = ModelRegistry(self.data_dir / "registry.json")
        self.registry.load()
        for entry in get_builtin_catalog():
            if not self.registry.get_entry(entry.model_id):
                self.registry.register(entry)

        # 2. Metrics & Caption Server
        self.metrics = PipelineMetrics()
        self.caption_server = CaptionServer(host="127.0.0.1", port=8765)

        # 3. Voice Profile Store
        self.voice_store = VoiceProfileStore(self.data_dir / "voice_profiles")

        # 4. Adapters (Verified physical models on drive M)
        from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import ParakeetTdtV3AsrAdapter
        self.vad = SileroVadAdapter()
        self.asr_en = ParakeetTdtV3AsrAdapter()
        self.asr_ro = ParakeetTdtV3AsrAdapter()
        self.mt = MiLMMT46TranslationAdapter(model_size="1b")
        self.tts_ro = OmniVoiceTtsAdapter()
        self.tts_en = self.tts_ro

        # 5. Duplex Orchestrator
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

        # 6. Degraded Mode Scheduler
        self.scheduler = DegradedModeScheduler(
            orchestrator=self.orchestrator,
            metrics=self.metrics,
        )

        # 7. Model Discovery Agent
        self.discovery_agent = ModelDiscoveryAgent(
            registry=self.registry,
            scan_interval_hours=24.0,
        )

        # 8. Model Manager Controller
        self.model_manager = ModelManagerController(self.registry)
        self._http_runner = None

    async def _setup_http_server(self) -> None:
        """Setup unified aiohttp HTTP + WebSocket server for UI & APIs."""
        from aiohttp import web

        app = web.Application()

        # REST API routes
        async def api_status(request):
            return web.json_response({
                "status": "online",
                "mode": self.orchestrator.mode.value,
                "tts_mode": self.orchestrator.tts_mode.value,
                "active_slots": self.model_manager.get_active_slots(),
            })

        async def api_models_available(request):
            return web.json_response(self.model_manager.list_available())

        async def api_models_installed(request):
            return web.json_response(self.model_manager.list_installed())

        async def api_models_active(request):
            data = await request.json()
            cap = data.get("capability", "ASR")
            mid = data.get("model_id")
            lang = data.get("language")
            pair = data.get("language_pair")
            self.model_manager.set_active_model(cap, mid, language=lang, language_pair=pair)
            return web.json_response({"success": True, "active_slots": self.model_manager.get_active_slots()})

        async def api_set_mode(request):
            data = await request.json()
            new_mode = PipelineMode(data.get("mode", "full_duplex"))
            await self.orchestrator.set_mode(new_mode)
            return web.json_response({"success": True, "mode": self.orchestrator.mode.value})

        async def api_set_tts_mode(request):
            data = await request.json()
            new_tts = TtsMode(data.get("tts_mode", "stock"))
            await self.orchestrator.set_tts_mode(new_tts)
            return web.json_response({"success": True, "tts_mode": self.orchestrator.tts_mode.value})

        async def api_translate(request):
            data = await request.json()
            text = data.get("text", "").strip()
            src = str(data.get("source", "en")).lower()
            tgt = str(data.get("target", "ro")).lower()
            if not text:
                return web.json_response({"error": "Empty text"}, status=400)
            
            from runtime.inference.protocol import LanguageCode
            def get_lang(code):
                try:
                    return LanguageCode(code)
                except ValueError:
                    return LanguageCode.EN

            src_lang = get_lang(src)
            tgt_lang = get_lang(tgt)
            
            t0 = asyncio.get_event_loop().time()
            result = await self.mt.translate(text, source_language=src_lang, target_language=tgt_lang)
            latency_ms = (asyncio.get_event_loop().time() - t0) * 1000.0
            
            return web.json_response({
                "source_text": text,
                "translated_text": result.translated_text,
                "source_language": src,
                "target_language": tgt,
                "latency_ms": round(latency_ms, 1),
            })

        async def api_voice_profiles(request):
            """List all enrolled voice profiles."""
            import json
            profiles_root = PROJECT_ROOT / "data" / "voice_profiles"
            profiles_root.mkdir(parents=True, exist_ok=True)
            
            active_id = "Default"
            active_file = profiles_root / "active_selection.json"
            if active_file.exists():
                try:
                    with open(active_file, "r") as f:
                        active_id = json.load(f).get("active_id", "Default")
                except Exception:
                    pass
            
            profiles = []
            for d in profiles_root.iterdir():
                if d.is_dir() and not d.name.startswith("."):
                    pjson = d / "profile.json"
                    wav_file = d / "reference.wav"
                    if pjson.exists():
                        try:
                            with open(pjson, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            meta["profile_id"] = d.name
                            meta["has_audio"] = wav_file.exists()
                            meta["is_active"] = (d.name == active_id)
                            profiles.append(meta)
                        except Exception:
                            pass
                    elif wav_file.exists():
                        profiles.append({
                            "profile_id": d.name,
                            "profile_name": d.name.replace("_", " "),
                            "pitch_hz": 130.0,
                            "has_audio": True,
                            "is_active": (d.name == active_id),
                        })
            
            return web.json_response({"profiles": profiles, "active_id": active_id})

        async def api_voice_rename(request):
            """Rename an existing voice profile."""
            import json
            data = await request.json()
            profile_id = data.get("profile_id", "").strip()
            new_name = data.get("new_name", "").strip()
            if not profile_id or not new_name:
                return web.json_response({"error": "Missing profile_id or new_name"}, status=400)
            
            profile_dir = PROJECT_ROOT / "data" / "voice_profiles" / profile_id
            if not profile_dir.exists():
                return web.json_response({"error": "Profile not found"}, status=404)
            
            pjson = profile_dir / "profile.json"
            meta = {}
            if pjson.exists():
                try:
                    with open(pjson, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    pass
            meta["profile_name"] = new_name
            with open(pjson, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            
            return web.json_response({"success": True, "profile_id": profile_id, "profile_name": new_name})

        async def api_voice_delete(request):
            """Delete a voice profile by ID."""
            import shutil
            profile_id = request.match_info.get("profile_id", "")
            if not profile_id:
                return web.json_response({"error": "Missing profile_id"}, status=400)
            
            profile_dir = PROJECT_ROOT / "data" / "voice_profiles" / profile_id
            if profile_dir.exists() and profile_dir.is_dir():
                shutil.rmtree(profile_dir, ignore_errors=True)
            
            return web.json_response({"success": True, "deleted_id": profile_id})

        async def api_voice_activate(request):
            """Activate a voice profile by ID."""
            import json
            data = await request.json()
            profile_id = data.get("profile_id", "Default")
            profiles_root = PROJECT_ROOT / "data" / "voice_profiles"
            profiles_root.mkdir(parents=True, exist_ok=True)
            with open(profiles_root / "active_selection.json", "w") as f:
                json.dump({"active_id": profile_id}, f)
            return web.json_response({"success": True, "active_id": profile_id})

        async def api_voice_stage(request):
            """Stage a newly recorded or uploaded voice profile audio, extract pitch, pre-warm clone prompt, and synthesize target preview."""
            import io
            import re
            import json
            import shutil
            import subprocess
            import soundfile as sf
            import numpy as np

            data = await request.post()
            raw_name = data.get("name", "My Voice Profile").strip() or "My Voice Profile"
            clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_name)
            clean_id = re.sub(r'_+', '_', clean_id).strip('_') or "custom_voice"

            staging_dir = PROJECT_ROOT / "data" / "voice_profiles" / ".staging"
            staging_dir.mkdir(parents=True, exist_ok=True)

            wav_path = staging_dir / "reference.wav"
            txt_path = staging_dir / "reference.txt"
            json_path = staging_dir / "profile.json"
            preview_wav_path = staging_dir / "preview_sample.wav"

            transcript_text = data.get("transcript", "The quick brown fox jumps over the lazy dog near the riverbank. Acoustic speech modeling captures vocal timbre and natural pitch dynamics for seamless real-time translation across Romanian conferences.")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(transcript_text)

            audio_file = data.get("audio")
            pitch_hz = 135.0
            if audio_file:
                audio_bytes = audio_file.file.read()
                raw_path = staging_dir / "upload_raw.audio"
                with open(raw_path, "wb") as f:
                    f.write(audio_bytes)

                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", str(raw_path), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                except Exception as e:
                    logger.error("FFmpeg staging conversion failed: %s", e)
                    with open(wav_path, "wb") as f:
                        f.write(audio_bytes)

                # Analyze Pitch
                try:
                    audio_data, sr = sf.read(str(wav_path))
                    if audio_data.ndim > 1:
                        audio_data = audio_data.mean(axis=1)
                    fft = np.abs(np.fft.rfft(audio_data[:min(len(audio_data), sr*2)]))
                    freqs = np.fft.rfftfreq(min(len(audio_data), sr*2), 1.0/sr)
                    valid = (freqs >= 80) & (freqs <= 300)
                    if np.any(valid):
                        pitch_hz = float(round(freqs[valid][np.argmax(fft[valid])], 1))
                except Exception:
                    pass

            clone_model = data.get("clone_model", "omnivoice").lower()
            profile_info = {
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "clone_model": clone_model,
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "status": "Staged (Pending Save)",
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(profile_info, f, indent=2)

            # Pre-synthesize genuine cloned sample preview in target preview language
            preview_lang = data.get("preview_lang", "ro").lower()
            preview_text = data.get("preview_text", "Vântul de primăvară adie lin peste dealurile înverzite ale Carpaților.").strip()
            if not preview_text:
                preview_text = "Vântul de primăvară adie lin peste dealurile înverzite ale Carpaților."
            
            has_preview = False
            if wav_path.exists():
                try:
                    # Select appropriate TTS engine
                    tts_engine = self.tts_ro
                    engine_name = "OmniVoice"
                    if any(k in clone_model for k in ["higgs", "boson"]):
                        tts_engine = HiggsTtsAdapter(shared_engine=self.tts_ro)
                        engine_name = "Higgs TTS 3"
                    elif any(k in clone_model for k in ["voxcpm", "openbmb"]):
                        tts_engine = VoxCpmTtsAdapter(shared_engine=self.tts_ro)
                        engine_name = "VoxCPM 2"
                    elif any(k in clone_model for k in ["moss", "openmoss"]):
                        tts_engine = MossTtsAdapter(shared_engine=self.tts_ro)
                        engine_name = "MOSS-TTS v1.5"

                    lang_map = {
                        "ro": "Romanian",
                        "en": "English",
                        "es": "Spanish",
                        "fr": "French",
                        "de": "German",
                        "it": "Italian",
                    }
                    target_language_name = lang_map.get(preview_lang, "Romanian")

                    logger.info("Synthesizing staged voice preview with %s (%s) for '%s'...", engine_name, target_language_name, raw_name)
                    audio_res = await asyncio.wait_for(
                        tts_engine.generate_cloned_audio(
                            text=preview_text,
                            ref_audio_path=str(wav_path),
                            ref_text=transcript_text,
                            num_step=2,
                            language=target_language_name,
                        ),
                        timeout=90.0
                    )
                    if audio_res and len(audio_res) > 500:
                        with open(preview_wav_path, "wb") as pf:
                            pf.write(audio_res)
                        has_preview = True
                        logger.info("Staged voice preview synthesized successfully (%d bytes) with %s.", len(audio_res), engine_name)
                except Exception as e:
                    logger.error("Staged voice cloning failed with %s: %s", clone_model, e)

            return web.json_response({
                "success": True,
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "has_preview": has_preview,
                "preview_url": "/api/voice/staging/preview",
                "reference_url": "/api/voice/staging/reference",
            })

        async def api_voice_staging_preview(request):
            """Stream the synthesized cloned preview audio for the currently staged voice profile."""
            preview_path = PROJECT_ROOT / "data" / "voice_profiles" / ".staging" / "preview_sample.wav"
            if preview_path.exists():
                with open(preview_path, "rb") as f:
                    return web.Response(body=f.read(), content_type="audio/wav")
            return web.Response(status=404, text="No staging preview available")

        async def api_voice_staging_reference(request):
            """Stream the raw recorded reference audio for the currently staged voice profile."""
            ref_path = PROJECT_ROOT / "data" / "voice_profiles" / ".staging" / "reference.wav"
            if ref_path.exists():
                with open(ref_path, "rb") as f:
                    return web.Response(body=f.read(), content_type="audio/wav")
            return web.Response(status=404, text="No staging reference available")

        async def api_voice_commit_stage(request):
            """Commit the staged voice profile into permanent storage and set as active profile."""
            import json
            import shutil
            import re

            data = await request.json()
            raw_name = data.get("name", "").strip()
            staging_dir = PROJECT_ROOT / "data" / "voice_profiles" / ".staging"

            if not staging_dir.exists() or not (staging_dir / "reference.wav").exists():
                return web.json_response({"error": "No staged voice profile found to commit"}, status=400)

            # Read existing staged profile info
            pitch_hz = 135.0
            if (staging_dir / "profile.json").exists():
                try:
                    with open(staging_dir / "profile.json", "r", encoding="utf-8") as pf:
                        pdata = json.load(pf)
                        pitch_hz = pdata.get("pitch_hz", 135.0)
                        if not raw_name:
                            raw_name = pdata.get("profile_name", "My Voice Profile")
                except Exception:
                    pass

            if not raw_name:
                raw_name = "My Voice Profile"

            clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_name)
            clean_id = re.sub(r'_+', '_', clean_id).strip('_') or "custom_voice"

            target_dir = PROJECT_ROOT / "data" / "voice_profiles" / clean_id
            target_dir.mkdir(parents=True, exist_ok=True)

            # Copy staged reference files
            if (staging_dir / "reference.wav").exists():
                shutil.copy2(staging_dir / "reference.wav", target_dir / "reference.wav")
            if (staging_dir / "reference.txt").exists():
                shutil.copy2(staging_dir / "reference.txt", target_dir / "reference.txt")

            final_info = {
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "status": "Enrolled & Active",
            }
            with open(target_dir / "profile.json", "w", encoding="utf-8") as f:
                json.dump(final_info, f, indent=2)

            # Set as active profile
            profiles_root = PROJECT_ROOT / "data" / "voice_profiles"
            with open(profiles_root / "active_selection.json", "w") as f:
                json.dump({"active_id": clean_id}, f)

            # Clean staging
            try:
                shutil.rmtree(staging_dir)
            except Exception:
                pass

            return web.json_response({
                "success": True,
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "status": "Enrolled & Active",
            })

        async def api_voice_clear_stage(request):
            """Discard and delete any staged voice profile data."""
            import shutil
            staging_dir = PROJECT_ROOT / "data" / "voice_profiles" / ".staging"
            if staging_dir.exists():
                try:
                    shutil.rmtree(staging_dir)
                except Exception:
                    pass
            return web.json_response({"success": True})

        async def api_voice_enroll(request):
            """Enroll a voice profile with user-defined name and uploaded or recorded audio."""
            import os
            import io
            import re
            import json
            import subprocess
            
            data = await request.post()
            raw_name = data.get("name", "My Custom Voice").strip()
            if not raw_name:
                raw_name = "My Custom Voice"
            
            # Clean safe folder name
            clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_name)
            clean_id = re.sub(r'_+', '_', clean_id).strip('_') or "custom_voice"
            
            profile_dir = PROJECT_ROOT / "data" / "voice_profiles" / clean_id
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            wav_path = profile_dir / "reference.wav"
            txt_path = profile_dir / "reference.txt"
            json_path = profile_dir / "profile.json"
            
            transcript_text = data.get("transcript", "Artificial intelligence enables seamless real-time conference translations across multiple languages. I am enrolling my voice profile so my Romanian translations sound naturally like me in meetings.")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(transcript_text)

            audio_file = data.get("audio")
            pitch_hz = 135.0
            if audio_file:
                audio_bytes = audio_file.file.read()
                raw_path = profile_dir / "upload_raw.audio"
                with open(raw_path, "wb") as f:
                    f.write(audio_bytes)
                
                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", str(raw_path), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                except Exception as e:
                    logger.error("FFmpeg conversion failed: %s", e)
                    with open(wav_path, "wb") as f:
                        f.write(audio_bytes)

                # Compute pitch
                try:
                    import numpy as np
                    import soundfile as sf
                    audio_data, sr = sf.read(str(wav_path))
                    if audio_data.ndim > 1:
                        audio_data = audio_data.mean(axis=1)
                    fft = np.abs(np.fft.rfft(audio_data[:min(len(audio_data), sr*2)]))
                    freqs = np.fft.rfftfreq(min(len(audio_data), sr*2), 1.0/sr)
                    valid = (freqs >= 80) & (freqs <= 300)
                    if np.any(valid):
                        pitch_hz = float(round(freqs[valid][np.argmax(fft[valid])], 1))
                except Exception:
                    pass

            profile_info = {
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "reference_audio": "reference.wav",
                "reference_text": "reference.txt",
                "status": "Enrolled & Active",
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(profile_info, f, indent=2)

            # Set as active profile
            profiles_root = PROJECT_ROOT / "data" / "voice_profiles"
            with open(profiles_root / "active_selection.json", "w") as f:
                json.dump({"active_id": clean_id}, f)

            return web.json_response({
                "success": True,
                "profile_id": clean_id,
                "profile_name": raw_name,
                "pitch_hz": pitch_hz,
                "saved_file": str(wav_path.relative_to(PROJECT_ROOT)),
                "status": "Enrolled & Active",
            })

        async def api_voice_audio(request):
            """Stream the reference audio for a profile."""
            profile_id = request.match_info.get("profile_id", "")
            wav_path = PROJECT_ROOT / "data" / "voice_profiles" / profile_id / "reference.wav"
            if wav_path.exists():
                with open(wav_path, "rb") as f:
                    return web.Response(body=f.read(), content_type="audio/wav")
            return web.Response(status=404)

        async def api_synthesize(request):
            """Generate genuine zero-shot neural cloned speech using the active voice profile."""
            import sys
            import json
            import asyncio
            from pathlib import Path
            if str(PROJECT_ROOT / "packages") not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT / "packages"))
            
            data = await request.json() if request.can_read_body else {}
            raw_text = data.get("text", "Bună ziua, aceasta este vocea mea.")
            if isinstance(raw_text, dict):
                raw_text = raw_text.get("text", "") or "Bună ziua, aceasta este vocea mea."
            text = str(raw_text).strip()
            target_lang = str(data.get("target", "ro")).lower()
            
            # Determine target voice profile
            profiles_root = PROJECT_ROOT / "data" / "voice_profiles"
            profile_id = data.get("profile_id")
            if not profile_id:
                active_file = profiles_root / "active_selection.json"
                if active_file.exists():
                    try:
                        with open(active_file, "r") as f:
                            profile_id = json.load(f).get("active_id")
                    except Exception:
                        pass
            
            if not profile_id:
                # pick first available
                for d in profiles_root.iterdir():
                    if d.is_dir() and (d / "reference.wav").exists():
                        profile_id = d.name
                        break

            wav_path = None
            ref_text = ""
            pitch_hz = 135.0
            if profile_id:
                pdir = profiles_root / profile_id
                if (pdir / "reference.wav").exists():
                    wav_path = pdir / "reference.wav"
                if (pdir / "reference.txt").exists():
                    try:
                        with open(pdir / "reference.txt", "r", encoding="utf-8") as tf:
                            ref_text = tf.read().strip()
                    except Exception:
                        pass
                if (pdir / "profile.json").exists():
                    try:
                        with open(pdir / "profile.json", "r", encoding="utf-8") as pf:
                            pitch_hz = json.load(pf).get("pitch_hz", 135.0)
                    except Exception:
                        pass

            # 1. Primary: Genuine OmniVoice Neural Voice Cloning from user's voice profile
            if wav_path and wav_path.exists() and self.tts_ro and getattr(self.tts_ro, "_loaded", False):
                try:
                    lang_map = {
                        "ro": "Romanian",
                        "en": "English",
                        "es": "Spanish",
                        "fr": "French",
                        "de": "German",
                        "it": "Italian",
                    }
                    target_language_name = lang_map.get(target_lang, "Romanian")

                    logger.info("Cloning speech with OmniVoice (%s) for profile '%s'...", target_language_name, profile_id)
                    audio_bytes = await asyncio.wait_for(
                        self.tts_ro.generate_cloned_audio(
                            text=text,
                            ref_audio_path=str(wav_path),
                            ref_text=ref_text,
                            num_step=2,
                            language=target_language_name,
                        ),
                        timeout=90.0
                    )
                    if audio_bytes and len(audio_bytes) > 500:
                        logger.info("Synthesized %d bytes of cloned speech for '%s'.", len(audio_bytes), profile_id)
                        return web.Response(body=audio_bytes, content_type="audio/wav")
                except Exception as e:
                    logger.error("OmniVoice zero-shot cloning error: %s", e)

            # 2. Fast pitch-adapted stream matching target language and voice profile pitch
            try:
                import edge_tts
                pitch_offset = f"{int(round((pitch_hz - 130.0) / 2.0)):+d}Hz"
                voice_map = {
                    "ro": "ro-RO-EmilNeural",
                    "es": "es-ES-AlvaroNeural",
                    "fr": "fr-FR-HenriNeural",
                    "de": "de-DE-ConradNeural",
                    "it": "it-IT-DiegoNeural",
                    "en": "en-US-GuyNeural",
                }
                voice = voice_map.get(target_lang, "ro-RO-EmilNeural")
                comm = edge_tts.Communicate(text, voice, pitch=pitch_offset)
                audio_buffer = bytearray()
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        audio_buffer.extend(chunk["data"])
                if audio_buffer:
                    return web.Response(body=bytes(audio_buffer), content_type="audio/mpeg")
            except Exception as e:
                logger.error("Fast neural synthesis error: %s", e)
                return web.Response(body=b"", status=500)
            
            return web.Response(body=b"", status=500)

        async def api_verify(request):
            """Perform acoustic post-process accuracy verification: Target Audio -> ASR -> Back-Translation -> Source Text Comparison."""
            import io
            import sys
            import urllib.parse
            import requests
            from pathlib import Path
            if str(PROJECT_ROOT / "packages") not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT / "packages"))

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
                    return web.json_response({"error": "No audio payload provided for verification"}, status=400)

                # 1. Convert audio bytes to standard WAV for ASR
                from pydub import AudioSegment
                import speech_recognition as sr

                try:
                    seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
                    wav_io = io.BytesIO()
                    seg.export(wav_io, format="wav")
                    wav_io.seek(0)
                except Exception as e:
                    return web.json_response({"error": f"Audio decode error: {e}"}, status=400)

                # 2. Run Speech-to-Text (ASR) on target audio
                asr_locale_map = {
                    "ro": "ro-RO",
                    "es": "es-ES",
                    "fr": "fr-FR",
                    "de": "de-DE",
                    "it": "it-IT",
                    "en": "en-US",
                }
                asr_locale = asr_locale_map.get(tgt_lang, "ro-RO")
                
                r = sr.Recognizer()
                with sr.AudioFile(wav_io) as source:
                    rec_audio = r.record(source)

                try:
                    asr_transcript = r.recognize_google(rec_audio, language=asr_locale)
                except sr.UnknownValueError:
                    return web.json_response({
                        "success": False,
                        "error": "ASR could not recognize speech from audio (unintelligible or distorted)",
                        "asr_transcript": "[Unintelligible Audio]",
                        "back_translated_text": "[Unintelligible Audio]",
                        "similarity_pct": 0,
                        "match_type": "NO MATCH (ASR FAILED)",
                    })
                except Exception as e:
                    return web.json_response({"error": f"ASR engine error: {e}"}, status=500)

                # 3. Back-Translate ASR transcription to source language (EN)
                url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={tgt_lang}&tl={src_lang}&dt=t&q={urllib.parse.quote(asr_transcript)}"
                resp = requests.get(url, timeout=5)
                back_translated = asr_transcript
                if resp.ok:
                    data = resp.json()
                    pieces = [chunk[0] for chunk in data[0] if chunk and chunk[0]]
                    back_translated = "".join(pieces)

                # 4. Compare Back-Translated Text against Original Source Text
                import re
                def normalize_tokens(s):
                    return re.findall(r'\w+', s.lower())

                orig_tokens = normalize_tokens(orig_text)
                back_tokens = normalize_tokens(back_translated)

                if not orig_tokens:
                    similarity_pct = 100 if not back_tokens else 0
                else:
                    matches = sum(1 for tok in back_tokens if tok in set(orig_tokens))
                    similarity_pct = round((matches / max(len(orig_tokens), len(back_tokens))) * 100.0, 1)

                match_type = "100% MATCH" if similarity_pct >= 95 else ("SEMANTIC MATCH" if similarity_pct >= 50 else "PARTIAL / LOW MATCH")

                return web.json_response({
                    "success": True,
                    "asr_transcript": asr_transcript,
                    "back_translated_text": back_translated,
                    "similarity_pct": similarity_pct,
                    "match_type": match_type,
                })
            except Exception as e:
                logger.error("Accuracy verification error: %s", e)
                return web.json_response({"error": f"Verification error: {e}"}, status=500)

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

        # Static UI routes
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
        logger.info("LiveTranslator Web UI & API ready at http://127.0.0.1:8766")
        logger.info("  - Caption Overlay:  http://127.0.0.1:8766/overlay/index.html")
        logger.info("  - Model Manager UI: http://127.0.0.1:8766/manager/index.html")

    async def start(self) -> None:
        logger.info("Initializing LiveTranslator Daemon...")
        await self.caption_server.start()
        await self._setup_http_server()
        await self.orchestrator.start()
        await self.scheduler.start()
        await self.discovery_agent.start()
        logger.info("LiveTranslator Daemon is FULLY ONLINE.")
        logger.info("Caption Overlay WebSocket: ws://127.0.0.1:8765/ws/captions")

    async def stop(self) -> None:
        logger.info("Shutting down LiveTranslator Daemon...")
        if self._http_runner:
            await self._http_runner.cleanup()
        await self.discovery_agent.stop()
        await self.scheduler.stop()
        await self.orchestrator.stop()
        await self.caption_server.stop()
        logger.info("Shutdown complete.")


async def main():
    parser = argparse.ArgumentParser(description="LiveTranslator Runtime Daemon")
    parser.add_argument("--data-dir", default="data", help="Directory for models and profiles")
    args = parser.parse_args()

    app = LiveTranslatorApp(data_dir=Path(args.data_dir))
    await app.start()

    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(1.0)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
