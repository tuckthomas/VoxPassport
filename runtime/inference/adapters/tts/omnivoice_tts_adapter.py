"""
VoxPassport — OmniVoice TTS Adapter
===================================
Real k2-fsa OmniVoice inference for multilingual zero-shot voice cloning.

Important quality guardrails:
  - OmniVoice upstream defaults to 32 iterative decoding steps and recommends
    16 for faster inference. The previous VoxPassport implementation forced
    2 steps, which can severely damage intelligibility.
  - Reference-prompt preprocessing, denoising, and output post-processing use
    the upstream quality defaults instead of being explicitly disabled.
  - A missing reference transcript is never replaced with invented text.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.protocol import (
    LanguageCode,
    SampleFormat,
    TtsAudioChunk,
    VoiceSpec,
)

logger = logging.getLogger(__name__)


class OmniVoiceTtsAdapter(TtsAdapter):
    """TTS adapter for k2-fsa OmniVoice."""

    ADAPTER_NAME = "OmniVoiceTtsAdapter"
    _NATIVE_SAMPLE_RATE_HZ = 24000
    _DEFAULT_QUALITY_STEPS = 32
    _MIN_QUALITY_STEPS = 16

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
    ):
        self._model_path = model_path
        self._device = device
        self._model = None
        self._loaded = False
        self._speaker_cache: dict[str, object] = {}

    async def load(self) -> None:
        if self._loaded:
            return
        logger.info("Loading OmniVoice TTS...")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_blocking)
        if self._model is None:
            raise RuntimeError("OmniVoice failed to load; inspect the preceding log output.")
        self._loaded = True
        logger.info("OmniVoice TTS loaded.")

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
        model_target = (
            str(local_candidate)
            if local_candidate.exists()
            else (self._model_path or "k2-fsa/OmniVoice")
        )

        use_cuda = torch.cuda.is_available() and self._device != "cpu"
        device_map = "cuda:0" if use_cuda else "cpu"
        dtype = torch.float16 if use_cuda else torch.float32

        logger.info("Loading neural OmniVoice from %s on %s...", model_target, device_map)
        try:
            self._model = OmniVoice.from_pretrained(
                model_target,
                device_map=device_map,
                dtype=dtype,
            )
            sample_rate = getattr(self._model, "sampling_rate", None)
            if sample_rate:
                self._NATIVE_SAMPLE_RATE_HZ = int(sample_rate)
            logger.info("OmniVoice neural TTS loaded on %s.", device_map)
            self._prewarm_saved_profiles(project_root)
        except Exception as exc:
            logger.exception("Failed to load OmniVoice model: %s", exc)
            self._model = None

    def _prewarm_saved_profiles(self, project_root: Path) -> None:
        """Cache valid saved reference prompts without inventing transcripts."""
        if self._model is None:
            return

        profiles_dir = project_root / "data" / "voice_profiles"
        if not profiles_dir.exists():
            return

        for profile_dir in profiles_dir.iterdir():
            if not profile_dir.is_dir() or profile_dir.name.startswith("."):
                continue

            ref_audio = profile_dir / "reference.wav"
            ref_text_file = profile_dir / "reference.txt"
            if not ref_audio.exists() or not ref_text_file.exists():
                continue

            try:
                ref_text = ref_text_file.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning("Could not read transcript for %s: %s", profile_dir.name, exc)
                continue

            if not ref_text:
                logger.warning(
                    "Skipping OmniVoice prewarm for '%s': reference transcript is empty.",
                    profile_dir.name,
                )
                continue

            cache_key = self._cache_key(str(ref_audio), ref_text)
            if cache_key in self._speaker_cache:
                continue

            try:
                logger.info("Pre-warming OmniVoice profile '%s'...", profile_dir.name)
                self._speaker_cache[cache_key] = self._model.create_voice_clone_prompt(
                    ref_audio=str(ref_audio),
                    ref_text=ref_text,
                    preprocess_prompt=True,
                )
            except Exception as exc:
                logger.warning("Failed to pre-warm '%s': %s", profile_dir.name, exc)

    @staticmethod
    def _cache_key(ref_audio_path: str, ref_text: str) -> str:
        return f"{Path(ref_audio_path).resolve()}::{ref_text.strip()}"

    @classmethod
    def _quality_steps(cls, requested_steps: int) -> int:
        """Reject the old two-step shortcut that corrupted speech quality."""
        try:
            steps = int(requested_steps)
        except (TypeError, ValueError):
            return cls._DEFAULT_QUALITY_STEPS

        if steps < cls._MIN_QUALITY_STEPS:
            logger.warning(
                "Requested OmniVoice num_step=%s is below the upstream fast-quality "
                "recommendation. Using %s steps instead.",
                steps,
                cls._DEFAULT_QUALITY_STEPS,
            )
            return cls._DEFAULT_QUALITY_STEPS
        return steps

    async def unload(self) -> None:
        logger.info("Unloading OmniVoice TTS.")
        self._speaker_cache.clear()
        self._model = None
        self._loaded = False

    async def synthesize_stream(
        self,
        text: str,
        language: LanguageCode,
        voice: VoiceSpec,
    ) -> AsyncIterator[TtsAudioChunk]:
        """Streaming transport remains separate from the preview cloning path."""
        if not self._loaded:
            raise RuntimeError("OmniVoiceTtsAdapter not loaded.")
        utterance_id = str(uuid.uuid4())
        segment_id = str(uuid.uuid4())
        yield TtsAudioChunk(
            utterance_id=utterance_id,
            segment_id=segment_id,
            sequence=0,
            sample_rate_hz=self._NATIVE_SAMPLE_RATE_HZ,
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
        """Generate cloned speech from the actual reference audio and transcript."""
        import soundfile as sf
        from omnivoice import OmniVoiceGenerationConfig

        if not self._loaded or self._model is None:
            raise RuntimeError("OmniVoice neural model not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")
        if not Path(ref_audio_path).exists():
            raise FileNotFoundError(f"Reference audio does not exist: {ref_audio_path}")

        clean_ref_text = (ref_text or "").strip()
        if not clean_ref_text:
            raise ValueError(
                "OmniVoice cloning requires the real transcript of the reference clip. "
                "VoxPassport will not substitute fabricated reference text."
            )

        effective_steps = self._quality_steps(num_step)
        loop = asyncio.get_running_loop()

        def _generate() -> bytes:
            cache_key = self._cache_key(ref_audio_path, clean_ref_text)
            prompt = self._speaker_cache.get(cache_key)
            if prompt is None:
                prompt = self._model.create_voice_clone_prompt(
                    ref_audio=ref_audio_path,
                    ref_text=clean_ref_text,
                    preprocess_prompt=True,
                )
                self._speaker_cache[cache_key] = prompt

            cfg = OmniVoiceGenerationConfig(
                num_step=effective_steps,
                denoise=True,
                preprocess_prompt=True,
                postprocess_output=True,
            )
            audio = self._model.generate(
                text=text.strip(),
                language=language or None,
                voice_clone_prompt=prompt,
                generation_config=cfg,
            )
            if not audio:
                raise RuntimeError("OmniVoice returned no audio.")

            sample_rate = int(
                getattr(self._model, "sampling_rate", None)
                or self._NATIVE_SAMPLE_RATE_HZ
            )
            buf = io.BytesIO()
            sf.write(buf, audio[0], sample_rate, format="WAV")
            return buf.getvalue()

        return await loop.run_in_executor(None, _generate)

    async def enroll_voice(
        self,
        voice_profile_id: str,
        reference_audio: bytes,
        reference_sample_rate_hz: int,
    ) -> None:
        """VoiceProfileStore persists enrollment audio; prompt caching occurs on synthesis."""
        if not self._loaded:
            raise RuntimeError("OmniVoiceTtsAdapter not loaded.")
        logger.info("Enrollment requested for voice profile: %s", voice_profile_id)

    def evict_voice_profile(self, voice_profile_id: str) -> None:
        # Cache keys are based on reference path + transcript rather than profile ID.
        self._speaker_cache.clear()
        logger.info("Cleared cached OmniVoice prompts after evicting %s", voice_profile_id)

    async def supports_voice_cloning(self) -> bool:
        return True

    async def supports_language(self, language: LanguageCode) -> bool:
        # OmniVoice supports hundreds of languages; the app's LanguageCode enum
        # determines which ones VoxPassport currently exposes.
        return True

    @property
    def native_sample_rate_hz(self) -> int:
        return self._NATIVE_SAMPLE_RATE_HZ

    async def health_check(self) -> bool:
        return self._loaded and self._model is not None

    def __repr__(self) -> str:
        return (
            f"OmniVoiceTtsAdapter(device={self._device!r}, loaded={self._loaded}, "
            f"cached_profiles={len(self._speaker_cache)})"
        )
