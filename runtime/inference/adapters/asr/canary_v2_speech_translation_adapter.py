"""
LiveTranslator — Canary-1B-v2 Direct Speech Translation Adapter
================================================================
Experimental adapter for NVIDIA Canary-1B-v2.

Model:  NVIDIA Canary-1B-v2
Source: https://huggingface.co/nvidia/canary-1b-v2
License: CC BY 4.0
Runtime: NVIDIA NeMo

This adapter tests the direct ASR→translation path (speech → translated text)
as an alternative to the modular ASR → MT → TTS pipeline.

Do NOT make this the default until it demonstrates:
  - Acceptable latency for conversational use
  - Acceptable Romanian translation quality (not just EN accuracy)
  - Streaming behavior compatible with PhraseCommitter
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from runtime.inference.adapters.base import DirectSpeechTranslationAdapter
from runtime.inference.protocol import (
    AudioFrame,
    LanguageCode,
    TranslationResult,
)

logger = logging.getLogger(__name__)

_UPSTREAM_MODEL_ID = "nvidia/canary-1b-v2"


class CanaryV2SpeechTranslationAdapter(DirectSpeechTranslationAdapter):
    """
    Experimental direct speech translation using NVIDIA Canary-1B-v2.

    Benchmarked as an alternative to the modular ASR+MT pipeline.
    """

    ADAPTER_NAME = "CanaryV2SpeechTranslationAdapter"

    def __init__(
        self,
        model_id: str = _UPSTREAM_MODEL_ID,
        device: str = "cuda",
    ):
        self._model_id = model_id
        self._device = device
        self._model = None
        self._loaded = False

    async def load(self) -> None:
        logger.info("Loading Canary-1B-v2... model_id=%s", self._model_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_blocking)
        self._loaded = True
        logger.info("Canary-1B-v2 loaded.")

    def _load_blocking(self) -> None:
        # TODO: Implement after model card verification.
        # Expected NeMo pattern:
        #   import nemo.collections.asr as nemo_asr
        #   self._model = nemo_asr.models.EncDecMultiTaskModel.from_pretrained(self._model_id)
        #   self._model = self._model.to(self._device).eval()
        logger.warning("CanaryV2SpeechTranslationAdapter._load_blocking: STUB.")

    async def unload(self) -> None:
        self._model = None
        self._loaded = False

    async def translate_audio(
        self,
        frame: AudioFrame,
        source_language: LanguageCode,
        target_language: LanguageCode,
    ) -> TranslationResult:
        """
        Translate audio directly to target-language text.
        Stub — not yet implemented.
        """
        # TODO: Buffer frames and call model inference when VAD signals utterance end.
        logger.warning("CanaryV2SpeechTranslationAdapter.translate_audio: STUB.")
        return TranslationResult(
            translated_text="",
            source_language=source_language,
            target_language=target_language,
            latency_ms=0.0,
        )

    async def health_check(self) -> bool:
        return self._loaded
