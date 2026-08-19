"""
LiveTranslator — OmniVoice TTS Adapter
=======================================
Wraps k2-fsa OmniVoice for streaming Romanian and English TTS synthesis.

Model family:  k2-fsa OmniVoice
Source:        https://github.com/k2-fsa/  (verify exact repo and model)
License:       CHECK UPSTREAM — must verify distribution rights before packaging
Runtime:       k2 / sherpa-onnx or native Python (verify from upstream)

Key requirements:
  - Stream audio chunks as soon as the model can emit them (minimize time-to-first-audio)
  - Cache speaker conditioning/prompt data after enrollment (do NOT recompute per sentence)
  - Support both stock (non-cloned) and zero-shot cloned voice
  - Expose native output sample rate
  - Support Romanian and English synthesis

Status: STUB — interface wired, inference not yet implemented.

IMPORTANT before implementing:
  - Verify exact OmniVoice model download location and model format.
  - Verify Romanian language support quality (is it production-grade?).
  - Verify cross-lingual voice cloning behavior (English ref → Romanian output).
  - Verify distribution/packaging rights.
  - Test chunk boundary artifacts.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import AsyncIterator, Optional

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.protocol import (
    AudioFrame,
    LanguageCode,
    SampleFormat,
    TtsAudioChunk,
    VoiceSpec,
)

logger = logging.getLogger(__name__)

_OMNIVOICE_REPO_PLACEHOLDER = "k2-fsa/OmniVoice"  # UNVERIFIED — check actual repo
_OMNIVOICE_VERIFIED = False


class OmniVoiceTtsAdapter(TtsAdapter):
    """
    TTS adapter for k2-fsa OmniVoice.

    Supports:
      - Stock (non-cloned) Romanian and English synthesis
      - Zero-shot voice cloning (when voice profile is enrolled)
      - Streaming PCM output (chunks emitted as they are synthesized)

    Voice cloning notes:
      - Call enroll_voice() once to create a speaker profile.
      - Pass the profile ID in VoiceSpec for subsequent synthesis calls.
      - Never recompute the speaker prompt for every sentence — use cached conditioning.
      - Cross-lingual cloning (English reference → Romanian output) may introduce accent;
        benchmark and compare with stock voice before enabling as default.
    """

    ADAPTER_NAME = "OmniVoiceTtsAdapter"
    # OmniVoice native output sample rate — verify from model card
    _NATIVE_SAMPLE_RATE_HZ = 24000  # UNVERIFIED — set correct value after model verification

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
    ):
        self._model_path = model_path
        self._device = device
        self._model = None
        self._loaded = False
        # Cache of speaker conditioning tensors keyed by voice_profile_id
        self._speaker_cache: dict[str, object] = {}

        if not _OMNIVOICE_VERIFIED:
            logger.warning(
                "OmniVoiceTtsAdapter: upstream model not yet verified. "
                "See Section 46 of plan and benchmarks/tts_bakeoff.py."
            )

    async def load(self) -> None:
        if self._loaded:
            return
        logger.info("Loading OmniVoice TTS...")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_blocking)
        self._loaded = True
        logger.info("OmniVoice TTS loaded.")

    def _load_blocking(self) -> None:
        import sys
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[4]
        pkg_dir = str(project_root / "packages")
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)
        sys.modules["torchvision"] = None

        import torch
        from omnivoice import OmniVoice

        local_candidate = project_root / "models" / "omnivoice-stock"
        model_target = str(local_candidate) if local_candidate.exists() else (self._model_path or "k2-fsa/OmniVoice")

        logger.info("Loading neural OmniVoice TTS from %s...", model_target)
        try:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = OmniVoice.from_pretrained(model_target, device_map=device, dtype=torch.float32)
            logger.info("OmniVoice neural TTS loaded on %s.", device)
            
            # Pre-warm enrolled voice profiles into _speaker_cache
            try:
                profiles_dir = project_root / "data" / "voice_profiles"
                if profiles_dir.exists():
                    for pdir in profiles_dir.iterdir():
                        if pdir.is_dir() and not pdir.name.startswith(".") and (pdir / "reference.wav").exists():
                            ref_wav = str(pdir / "reference.wav")
                            ref_txt = ""
                            if (pdir / "reference.txt").exists():
                                try:
                                    with open(pdir / "reference.txt", "r", encoding="utf-8") as tf:
                                        ref_txt = tf.read().strip()
                                except Exception:
                                    pass
                            ckey = f"{ref_wav}_{ref_txt}"
                            if ckey not in self._speaker_cache:
                                logger.info("Pre-warming voice profile clone prompt for '%s'...", pdir.name)
                                self._speaker_cache[ckey] = self._model.create_voice_clone_prompt(
                                    ref_audio=ref_wav,
                                    ref_text=ref_txt or "Artificial intelligence enables seamless real-time conference translations across multiple languages. I am enrolling my voice profile so my Romanian translations sound naturally like me in meetings.",
                                    preprocess_prompt=False,
                                )
            except Exception as e:
                logger.warning("Failed to pre-warm voice profile prompts: %s", e)

        except Exception as e:
            logger.error("Failed to load OmniVoice model: %s", e)
            self._model = None

    async def unload(self) -> None:
        logger.info("Unloading OmniVoice TTS.")
        self._model = None
        self._loaded = False

    async def synthesize_stream(
        self,
        text: str,
        language: LanguageCode,
        voice: VoiceSpec,
    ) -> AsyncIterator[TtsAudioChunk]:
        """Synthesize text and yield PCM audio chunks."""
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
        num_step: int = 2,
        language: str = "Romanian",
    ) -> bytes:
        """Generate speech in cloned voice matching the reference audio file."""
        import io
        import soundfile as sf
        from omnivoice import OmniVoiceGenerationConfig
        
        loop = asyncio.get_running_loop()
        
        def _generate():
            if not self._model:
                raise RuntimeError("OmniVoice neural model not loaded.")
            
            # Cache speaker prompt for instant generation
            cache_key = f"{ref_audio_path}_{ref_text}"
            if cache_key not in self._speaker_cache:
                self._speaker_cache[cache_key] = self._model.create_voice_clone_prompt(
                    ref_audio=ref_audio_path,
                    ref_text=ref_text or "Artificial intelligence enables seamless real-time conference translations across multiple languages. I am enrolling my voice profile so my Romanian translations sound naturally like me in meetings.",
                    preprocess_prompt=False,
                )
            prompt = self._speaker_cache[cache_key]

            cfg = OmniVoiceGenerationConfig(num_step=num_step, preprocess_prompt=False, denoise=False)
            audio = self._model.generate(
                text=text,
                language=language or "Romanian",
                voice_clone_prompt=prompt,
                generation_config=cfg,
            )
            buf = io.BytesIO()
            sf.write(buf, audio[0], 24000, format='WAV')
            buf.seek(0)
            return buf.read()
            
        return await loop.run_in_executor(None, _generate)

    async def enroll_voice(
        self,
        voice_profile_id: str,
        reference_audio: bytes,
        reference_sample_rate_hz: int,
    ) -> None:
        """
        Enroll a speaker voice profile from a reference audio clip.

        Args:
            voice_profile_id: A unique ID for this speaker profile (caller-provided).
            reference_audio: PCM audio of the reference speaker (3-10 seconds of clean speech).
            reference_sample_rate_hz: Sample rate of reference_audio.

        The computed conditioning is cached in memory (not persisted here).
        Persistence with encryption is handled by the VoiceProfileStore layer.
        """
        if not self._loaded:
            raise RuntimeError("OmniVoiceTtsAdapter not loaded.")

        logger.info("Enrolling voice profile: %s", voice_profile_id)
        # TODO: Compute speaker conditioning from reference_audio using OmniVoice.
        # Cache the result in self._speaker_cache[voice_profile_id].
        logger.warning("OmniVoiceTtsAdapter.enroll_voice: STUB.")
        # Stub: store placeholder
        self._speaker_cache[voice_profile_id] = object()

    def evict_voice_profile(self, voice_profile_id: str) -> None:
        """Remove a cached speaker conditioning from memory."""
        removed = self._speaker_cache.pop(voice_profile_id, None)
        if removed:
            logger.info("Evicted voice profile from cache: %s", voice_profile_id)

    async def supports_voice_cloning(self) -> bool:
        # TODO: Verify this is True after implementing enroll_voice.
        return True  # OmniVoice is designed for zero-shot voice cloning

    async def supports_language(self, language: LanguageCode) -> bool:
        # TODO: Verify supported languages from OmniVoice model card.
        return language in (LanguageCode.EN, LanguageCode.RO)

    @property
    def native_sample_rate_hz(self) -> int:
        return self._NATIVE_SAMPLE_RATE_HZ

    async def health_check(self) -> bool:
        return self._loaded

    def __repr__(self) -> str:
        return (
            f"OmniVoiceTtsAdapter("
            f"device={self._device!r}, "
            f"loaded={self._loaded}, "
            f"cached_profiles={list(self._speaker_cache.keys())})"
        )
