"""OmniVoice TTS adapter for VoxPassport.

Voice profiles are engine-agnostic reference recordings. If OmniVoice is the
active TTS engine it conditions directly on the selected reference. Profile
conditioning is strictly lazy: model load never prewarms saved profiles, and at
most one clone prompt is retained so unused profiles cannot accumulate VRAM.
"""

from __future__ import annotations

import asyncio
import gc
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

    def __init__(self, model_path: Optional[str] = None, device: str = "cuda") -> None:
        self._model_path = model_path
        self._device = device
        self._model = None
        self._loaded = False
        self._speaker_cache: dict[str, object] = {}
        self._profiles_root = Path(__file__).resolve().parents[4] / "data" / "voice_profiles"

    @staticmethod
    def _release_cuda_cache() -> None:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    async def load(self) -> None:
        # Adapter activation is cheap. Weights stay lazy until OmniVoice is
        # actually asked to synthesize, preserving VRAM for ASR/live debugging.
        self._loaded = True

    async def _ensure_omnivoice_loaded(self) -> None:
        self._loaded = True
        if self._model is not None:
            return
        self._release_cuda_cache()
        await asyncio.get_running_loop().run_in_executor(None, self._load_blocking)
        if self._model is None:
            raise RuntimeError("OmniVoice failed to load; inspect the preceding runtime log")

    def _load_blocking(self) -> None:
        try:
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
            if use_cuda:
                gc.collect()
                torch.cuda.empty_cache()
            self._model = OmniVoice.from_pretrained(
                model_target,
                device_map="cuda:0" if use_cuda else "cpu",
                dtype=torch.float16 if use_cuda else torch.float32,
            )
            sample_rate = getattr(self._model, "sampling_rate", None)
            if sample_rate:
                self._NATIVE_SAMPLE_RATE_HZ = int(sample_rate)
            logger.info(
                "Loaded OmniVoice on %s with lazy voice-profile conditioning",
                "cuda:0" if use_cuda else "cpu",
            )
        except Exception as exc:
            self._model = None
            logger.exception("Failed to load OmniVoice: %s", exc)

    @classmethod
    def _quality_steps(cls, requested_steps: int) -> int:
        try:
            steps = int(requested_steps)
        except (TypeError, ValueError):
            return cls._DEFAULT_QUALITY_STEPS
        if steps < cls._MIN_QUALITY_STEPS:
            logger.warning("Refusing OmniVoice num_step=%s; using %s", steps, cls._DEFAULT_QUALITY_STEPS)
            return cls._DEFAULT_QUALITY_STEPS
        return steps

    @staticmethod
    def _cache_key(ref_audio_path: str, ref_text: str | None) -> str:
        return f"{Path(ref_audio_path).resolve()}::{(ref_text or '<auto-transcribe>').strip()}"

    def _resolve_profile_id(self, requested_id: Optional[str]) -> str:
        profile_id = str(requested_id or "").strip()
        if profile_id and profile_id.lower() not in {"active", "default"}:
            return profile_id
        active_file = self._profiles_root / "active_selection.json"
        if active_file.exists():
            try:
                import json
                active_id = str(json.loads(active_file.read_text(encoding="utf-8")).get("active_id", "")).strip()
                if active_id and active_id.lower() != "default":
                    return active_id
            except Exception:
                logger.exception("Could not read active voice-profile selection")
        raise ValueError("Cloned synthesis requires an active saved voice profile")

    def _profile_reference(self, voice: VoiceSpec) -> tuple[Path, str]:
        profile_id = self._resolve_profile_id(voice.voice_profile_id)
        profile_dir = self._profiles_root / profile_id
        ref_audio = profile_dir / "reference.wav"
        ref_text_file = profile_dir / "reference.txt"
        if not ref_audio.exists():
            raise FileNotFoundError(f"Voice profile {profile_id!r} has no reference.wav")
        ref_text = ref_text_file.read_text(encoding="utf-8").strip() if ref_text_file.exists() else ""
        return ref_audio, ref_text

    async def unload(self) -> None:
        # Clone prompts may themselves retain CUDA tensors; drop them before the
        # model and force collection before asking the allocator for its cache.
        self._speaker_cache.clear()
        old_model = self._model
        self._model = None
        self._loaded = False
        if old_model is not None:
            del old_model
        self._release_cuda_cache()

    async def synthesize_stream(
        self, text: str, language: LanguageCode, voice: VoiceSpec
    ) -> AsyncIterator[TtsAudioChunk]:
        import numpy as np
        import soundfile as sf

        if not self._loaded:
            raise RuntimeError("OmniVoiceTtsAdapter is not loaded")
        clean_text = str(text).strip()
        if not clean_text:
            raise ValueError("Target TTS text must not be empty")
        language_value = getattr(language, "value", str(language))

        if voice.is_cloned:
            ref_audio, ref_text = self._profile_reference(voice)
            wav_bytes = await self.generate_cloned_audio(
                text=clean_text,
                ref_audio_path=str(ref_audio),
                ref_text=ref_text,
                num_step=self._DEFAULT_QUALITY_STEPS,
                language=language_value,
            )
            audio, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
        else:
            await self._ensure_omnivoice_loaded()
            from omnivoice import OmniVoiceGenerationConfig

            def _generate_stock():
                import torch
                cfg = OmniVoiceGenerationConfig(
                    num_step=self._DEFAULT_QUALITY_STEPS,
                    denoise=True,
                    preprocess_prompt=True,
                    postprocess_output=True,
                )
                with torch.inference_mode():
                    result = self._model.generate(
                        text=clean_text,
                        language=language_value,
                        generation_config=cfg,
                        normalize_text=True,
                    )
                if not result:
                    raise RuntimeError("OmniVoice returned no stock audio")
                return result[0], int(getattr(self._model, "sampling_rate", None) or self._NATIVE_SAMPLE_RATE_HZ)

            audio, sample_rate = await asyncio.get_running_loop().run_in_executor(None, _generate_stock)

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=-1 if audio.shape[-1] < audio.shape[0] else 0)
        audio = np.ascontiguousarray(audio.reshape(-1), dtype="<f4")
        utterance_id, segment_id = str(uuid.uuid4()), str(uuid.uuid4())
        chunk_samples = max(1, int(sample_rate * 0.10))
        sequence = 0
        for offset in range(0, audio.size, chunk_samples):
            piece = audio[offset : offset + chunk_samples]
            yield TtsAudioChunk(
                utterance_id=utterance_id,
                segment_id=segment_id,
                sequence=sequence,
                sample_rate_hz=int(sample_rate),
                sample_format=SampleFormat.PCM_F32LE,
                data=piece.tobytes(),
                is_final_chunk=False,
            )
            sequence += 1
            await asyncio.sleep(0)
        yield TtsAudioChunk(
            utterance_id=utterance_id,
            segment_id=segment_id,
            sequence=sequence,
            sample_rate_hz=int(sample_rate),
            sample_format=SampleFormat.PCM_F32LE,
            data=b"",
            is_final_chunk=True,
        )

    async def generate_cloned_audio(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str = "",
        num_step: int = 32,
        language: str = "Romanian",
    ) -> bytes:
        import soundfile as sf
        from omnivoice import OmniVoiceGenerationConfig

        await self._ensure_omnivoice_loaded()
        clean_text = str(text).strip()
        if not clean_text:
            raise ValueError("Target TTS text must not be empty")
        if not Path(ref_audio_path).exists():
            raise FileNotFoundError(f"Reference audio does not exist: {ref_audio_path}")

        clean_ref_text = str(ref_text or "").strip()
        effective_steps = self._quality_steps(num_step)

        def _generate() -> bytes:
            import torch

            key = self._cache_key(ref_audio_path, clean_ref_text or None)
            prompt = self._speaker_cache.get(key)
            if prompt is None:
                # Keep exactly one conditioning prompt. Switching profiles evicts
                # the prior prompt rather than accumulating profile tensors.
                self._speaker_cache.clear()
                prompt = self._model.create_voice_clone_prompt(
                    ref_audio=ref_audio_path,
                    ref_text=clean_ref_text or None,
                    preprocess_prompt=True,
                )
                self._speaker_cache[key] = prompt
            cfg = OmniVoiceGenerationConfig(
                num_step=effective_steps,
                denoise=True,
                preprocess_prompt=True,
                postprocess_output=True,
            )
            with torch.inference_mode():
                result = self._model.generate(
                    text=clean_text,
                    language=language or None,
                    voice_clone_prompt=prompt,
                    generation_config=cfg,
                    normalize_text=True,
                )
            if not result:
                raise RuntimeError("OmniVoice returned no cloned audio")
            sample_rate = int(getattr(self._model, "sampling_rate", None) or self._NATIVE_SAMPLE_RATE_HZ)
            buf = io.BytesIO()
            sf.write(buf, result[0], sample_rate, format="WAV")
            return buf.getvalue()

        try:
            return await asyncio.get_running_loop().run_in_executor(None, _generate)
        except Exception as exc:
            # CUDA OOM often leaves cached allocator blocks behind. Do not hide
            # the failure, but reclaim everything that is not still live.
            if "out of memory" in str(exc).lower():
                self._release_cuda_cache()
            raise

    async def enroll_voice(self, voice_profile_id: str, reference_audio: bytes, reference_sample_rate_hz: int) -> None:
        if not self._loaded:
            raise RuntimeError("OmniVoiceTtsAdapter is not loaded")

    def evict_voice_profile(self, voice_profile_id: str) -> None:
        self._speaker_cache.clear()
        self._release_cuda_cache()

    async def supports_voice_cloning(self) -> bool:
        return True

    async def supports_language(self, language: LanguageCode) -> bool:
        return True

    @property
    def native_sample_rate_hz(self) -> int:
        return self._NATIVE_SAMPLE_RATE_HZ

    async def health_check(self) -> bool:
        return self._loaded
