"""VoxPassport — OmniVoice TTS Adapter.

OmniVoice itself does not expose a native incremental vocoder stream through its
Python API. This adapter therefore performs real model generation, then emits
PCM chunks through the common TtsAdapter stream contract. Higgs and MOSS use
native server-side streaming; OmniVoice remains batch-generation/chunk-playback.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.protocol import LanguageCode, SampleFormat, TtsAudioChunk, VoiceSpec

logger = logging.getLogger(__name__)


class OmniVoiceTtsAdapter(TtsAdapter):
    ADAPTER_NAME = "OmniVoiceTtsAdapter"
    _NATIVE_SAMPLE_RATE_HZ = 24000
    _DEFAULT_QUALITY_STEPS = 32
    _MIN_QUALITY_STEPS = 16

    def __init__(self, model_path: Optional[str] = None, device: str = "cuda"):
        self._model_path = model_path
        self._device = device
        self._model = None
        self._loaded = False
        self._speaker_cache: dict[str, object] = {}
        self._profiles_root = Path(__file__).resolve().parents[4] / "data" / "voice_profiles"
        self._external_stream_engines: dict[str, TtsAdapter] = {}

    async def load(self) -> None:
        # Activate only. Load OmniVoice weights lazily on first OmniVoice use so a
        # Higgs/MOSS active profile does not consume VRAM for an unused model.
        self._loaded = True

    async def _ensure_omnivoice_loaded(self) -> None:
        self._loaded = True
        if self._model is not None:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_blocking)
        if self._model is None:
            raise RuntimeError("OmniVoice failed to load; inspect the preceding log.")

    def _load_blocking(self) -> None:
        import sys
        import torch
        project_root = Path(__file__).resolve().parents[4]
        pkg_dir = str(project_root / "packages")
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)
        sys.modules["torchvision"] = None
        from omnivoice import OmniVoice
        local_candidate = project_root / "models" / "omnivoice-stock"
        model_target = str(local_candidate) if local_candidate.exists() else (self._model_path or "k2-fsa/OmniVoice")
        use_cuda = torch.cuda.is_available() and self._device != "cpu"
        device_map = "cuda:0" if use_cuda else "cpu"
        dtype = torch.float16 if use_cuda else torch.float32
        try:
            self._model = OmniVoice.from_pretrained(model_target, device_map=device_map, dtype=dtype)
            sample_rate = getattr(self._model, "sampling_rate", None)
            if sample_rate:
                self._NATIVE_SAMPLE_RATE_HZ = int(sample_rate)
            self._prewarm_saved_profiles()
        except Exception as exc:
            logger.exception("Failed to load OmniVoice model: %s", exc)
            self._model = None

    def _prewarm_saved_profiles(self) -> None:
        if self._model is None or not self._profiles_root.exists():
            return
        for profile_dir in self._profiles_root.iterdir():
            if not profile_dir.is_dir() or profile_dir.name.startswith("."):
                continue
            ref_audio = profile_dir / "reference.wav"
            ref_text_file = profile_dir / "reference.txt"
            if not ref_audio.exists() or not ref_text_file.exists():
                continue
            ref_text = ref_text_file.read_text(encoding="utf-8").strip()
            if not ref_text:
                continue
            key = self._cache_key(str(ref_audio), ref_text)
            if key in self._speaker_cache:
                continue
            try:
                self._speaker_cache[key] = self._model.create_voice_clone_prompt(
                    ref_audio=str(ref_audio), ref_text=ref_text, preprocess_prompt=True
                )
            except Exception as exc:
                logger.warning("Failed to prewarm OmniVoice profile %s: %s", profile_dir.name, exc)

    @staticmethod
    def _cache_key(ref_audio_path: str, ref_text: str) -> str:
        return f"{Path(ref_audio_path).resolve()}::{ref_text.strip()}"

    @classmethod
    def _quality_steps(cls, requested_steps: int) -> int:
        try:
            steps = int(requested_steps)
        except (TypeError, ValueError):
            return cls._DEFAULT_QUALITY_STEPS
        if steps < cls._MIN_QUALITY_STEPS:
            logger.warning("Refusing OmniVoice num_step=%s; using %s quality steps.", steps, cls._DEFAULT_QUALITY_STEPS)
            return cls._DEFAULT_QUALITY_STEPS
        return steps

    def _resolve_profile_id(self, requested_id: Optional[str]) -> str:
        profile_id = (requested_id or "").strip()
        if profile_id and profile_id.lower() not in {"active", "default"}:
            return profile_id
        active_file = self._profiles_root / "active_selection.json"
        if active_file.exists():
            try:
                import json
                active_id = str(json.loads(active_file.read_text(encoding="utf-8")).get("active_id", "")).strip()
                if active_id and active_id.lower() != "default":
                    return active_id
            except Exception as exc:
                logger.warning("Could not resolve active voice profile: %s", exc)
        raise ValueError("Cloned synthesis requires an active saved voice profile.")

    def _profile_metadata(self, profile_id: str) -> dict:
        import json
        path = self._profiles_root / profile_id / "profile.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read profile metadata for %s: %s", profile_id, exc)
            return {}

    @staticmethod
    def _normalize_clone_model(name: str | None) -> str:
        value = str(name or "omnivoice").lower()
        if "higgs" in value or "boson" in value:
            return "higgs"
        if "moss" in value or "openmoss" in value:
            return "moss"
        if "voxcpm" in value or "openbmb" in value:
            return "voxcpm"
        return "omnivoice"

    async def _external_stream_engine(self, model: str) -> TtsAdapter:
        engine = self._external_stream_engines.get(model)
        if engine is not None:
            return engine
        if model == "higgs":
            from runtime.inference.adapters.tts.higgs_tts_adapter import HiggsTtsAdapter
            engine = HiggsTtsAdapter(profiles_root=self._profiles_root)
        elif model == "moss":
            from runtime.inference.adapters.tts.moss_tts_adapter import MossTtsAdapter
            engine = MossTtsAdapter(profiles_root=self._profiles_root)
        elif model == "voxcpm":
            from runtime.inference.adapters.tts.voxcpm_tts_adapter import VoxCpmTtsAdapter
            engine = VoxCpmTtsAdapter()
        else:
            return self
        await engine.load()
        self._external_stream_engines[model] = engine
        return engine

    def _profile_reference(self, voice: VoiceSpec) -> tuple[Path, str]:
        profile_id = self._resolve_profile_id(voice.voice_profile_id)
        profile_dir = self._profiles_root / profile_id
        ref_audio = profile_dir / "reference.wav"
        ref_text_file = profile_dir / "reference.txt"
        if not ref_audio.exists():
            raise FileNotFoundError(f"Voice profile '{profile_id}' has no reference.wav")
        ref_text = ref_text_file.read_text(encoding="utf-8").strip() if ref_text_file.exists() else ""
        if not ref_text:
            raise ValueError(f"Voice profile '{profile_id}' has no reference transcript.")
        return ref_audio, ref_text

    async def unload(self) -> None:
        for engine in list(self._external_stream_engines.values()):
            try:
                await engine.unload()
            except Exception:
                pass
        self._external_stream_engines.clear()
        self._speaker_cache.clear()
        self._model = None
        self._loaded = False

    async def synthesize_stream(self, text: str, language: LanguageCode, voice: VoiceSpec) -> AsyncIterator[TtsAudioChunk]:
        """Generate OmniVoice audio or dispatch cloned live speech to the saved backend."""
        import numpy as np
        import soundfile as sf
        if not self._loaded:
            raise RuntimeError("OmniVoiceTtsAdapter not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")
        language_value = getattr(language, "value", str(language))

        if voice.is_cloned:
            profile_id = self._resolve_profile_id(voice.voice_profile_id)
            clone_model = self._normalize_clone_model(self._profile_metadata(profile_id).get("clone_model", "omnivoice"))
            if clone_model != "omnivoice":
                engine = await self._external_stream_engine(clone_model)
                routed_voice = VoiceSpec(language=language, is_cloned=True, voice_profile_id=profile_id)
                async for chunk in engine.synthesize_stream(text=text, language=language, voice=routed_voice):
                    yield chunk
                return
            await self._ensure_omnivoice_loaded()
            ref_audio, ref_text = self._profile_reference(VoiceSpec(language=language, is_cloned=True, voice_profile_id=profile_id))
            wav_bytes = await self.generate_cloned_audio(
                text=text, ref_audio_path=str(ref_audio), ref_text=ref_text,
                num_step=self._DEFAULT_QUALITY_STEPS, language=language_value,
            )
            audio, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
        else:
            await self._ensure_omnivoice_loaded()
            from omnivoice import OmniVoiceGenerationConfig
            loop = asyncio.get_running_loop()
            def _generate_stock():
                cfg = OmniVoiceGenerationConfig(
                    num_step=self._DEFAULT_QUALITY_STEPS, denoise=True,
                    preprocess_prompt=True, postprocess_output=True,
                )
                result = self._model.generate(
                    text=text.strip(), language=language_value,
                    generation_config=cfg, normalize_text=True,
                )
                if not result:
                    raise RuntimeError("OmniVoice returned no stock audio.")
                return result[0], int(getattr(self._model, "sampling_rate", None) or self._NATIVE_SAMPLE_RATE_HZ)
            audio, sample_rate = await loop.run_in_executor(None, _generate_stock)

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=-1 if audio.shape[-1] < audio.shape[0] else 0)
        audio = np.ascontiguousarray(audio.reshape(-1), dtype="<f4")
        utterance_id = str(uuid.uuid4())
        segment_id = str(uuid.uuid4())
        chunk_samples = max(1, int(sample_rate * 0.10))
        sequence = 0
        for offset in range(0, audio.size, chunk_samples):
            piece = audio[offset:offset + chunk_samples]
            yield TtsAudioChunk(
                utterance_id=utterance_id, segment_id=segment_id, sequence=sequence,
                sample_rate_hz=int(sample_rate), sample_format=SampleFormat.PCM_F32LE,
                data=piece.tobytes(), is_final_chunk=False,
            )
            sequence += 1
            await asyncio.sleep(0)
        yield TtsAudioChunk(
            utterance_id=utterance_id, segment_id=segment_id, sequence=sequence,
            sample_rate_hz=int(sample_rate), sample_format=SampleFormat.PCM_F32LE,
            data=b"", is_final_chunk=True,
        )

    async def generate_cloned_audio(
        self, text: str, ref_audio_path: str, ref_text: str = "",
        num_step: int = 32, language: str = "Romanian",
    ) -> bytes:
        import soundfile as sf
        from omnivoice import OmniVoiceGenerationConfig
        await self._ensure_omnivoice_loaded()
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")
        if not Path(ref_audio_path).exists():
            raise FileNotFoundError(f"Reference audio does not exist: {ref_audio_path}")
        clean_ref_text = (ref_text or "").strip()
        if not clean_ref_text:
            raise ValueError("OmniVoice cloning requires the real transcript of the reference clip.")
        effective_steps = self._quality_steps(num_step)
        loop = asyncio.get_running_loop()
        def _generate() -> bytes:
            cache_key = self._cache_key(ref_audio_path, clean_ref_text)
            prompt = self._speaker_cache.get(cache_key)
            if prompt is None:
                prompt = self._model.create_voice_clone_prompt(
                    ref_audio=ref_audio_path, ref_text=clean_ref_text, preprocess_prompt=True
                )
                self._speaker_cache[cache_key] = prompt
            cfg = OmniVoiceGenerationConfig(
                num_step=effective_steps, denoise=True,
                preprocess_prompt=True, postprocess_output=True,
            )
            audio = self._model.generate(
                text=text.strip(), language=language or None,
                voice_clone_prompt=prompt, generation_config=cfg,
                normalize_text=True,
            )
            if not audio:
                raise RuntimeError("OmniVoice returned no audio.")
            sample_rate = int(getattr(self._model, "sampling_rate", None) or self._NATIVE_SAMPLE_RATE_HZ)
            buf = io.BytesIO()
            sf.write(buf, audio[0], sample_rate, format="WAV")
            return buf.getvalue()
        return await loop.run_in_executor(None, _generate)

    async def enroll_voice(self, voice_profile_id: str, reference_audio: bytes, reference_sample_rate_hz: int) -> None:
        if not self._loaded:
            raise RuntimeError("OmniVoiceTtsAdapter not loaded.")
        logger.info("Enrollment requested for voice profile: %s", voice_profile_id)

    def evict_voice_profile(self, voice_profile_id: str) -> None:
        self._speaker_cache.clear()

    async def supports_voice_cloning(self) -> bool:
        return True

    async def supports_language(self, language: LanguageCode) -> bool:
        return True

    @property
    def native_sample_rate_hz(self) -> int:
        return self._NATIVE_SAMPLE_RATE_HZ

    async def health_check(self) -> bool:
        return self._loaded
