"""
LiveTranslator — NVIDIA Riva-Translate-4B-Instruct-v2 Adapter
==============================================================
Quality comparator for EN↔RO translation.

Model:  NVIDIA Riva-Translate-4B-Instruct-v2
Source: https://huggingface.co/nvidia/  (verify exact model card)
License: NVIDIA Open Model License — verify terms before distribution
Runtime: NeMo or Transformers (verify from model card)

Status: STUB — quality comparator only. Not the default.

IMPORTANT:
  - Verify exact Hugging Face model ID.
  - Verify NVIDIA Open Model License commercial-use terms.
  - Track licensing separately from technical quality.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from runtime.inference.adapters.base import TranslationAdapter
from runtime.inference.protocol import (
    LanguageCode,
    TranslationContext,
    TranslationResult,
)

logger = logging.getLogger(__name__)

_UPSTREAM_MODEL_ID = "nvidia/riva-translate-4b-instruct-v2"  # UNVERIFIED
_MODEL_ID_VERIFIED = False


class RivaTranslate4BAdapter(TranslationAdapter):
    """
    Translation adapter for NVIDIA Riva-Translate-4B-Instruct-v2.

    Quality comparator against MiLMMT-46 1B and 4B.
    Promotes to default only if quality gain justifies VRAM/latency cost
    AND license terms are confirmed acceptable.
    """

    ADAPTER_NAME = "RivaTranslate4BAdapter"

    def __init__(
        self,
        model_id: str = _UPSTREAM_MODEL_ID,
        device: str = "cuda",
        max_new_tokens: int = 256,
    ):
        self._model_id = model_id
        self._device = device
        self._max_new_tokens = max_new_tokens
        self._model = None
        self._tokenizer = None
        self._loaded = False

        if not _MODEL_ID_VERIFIED:
            logger.warning(
                "RivaTranslate4BAdapter: model ID not verified. "
                "See Section 46 of plan."
            )

    async def load(self) -> None:
        logger.info("Loading Riva-Translate-4B... model_id=%s", self._model_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_blocking)
        self._loaded = True

    def _load_blocking(self) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            logger.info("Loading tokenizer for Riva-Translate-4B: %s...", self._model_id)
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_id, trust_remote_code=False)
            device = "cuda" if torch.cuda.is_available() and "cuda" in self._device else "cpu"
            logger.info("Loading Riva-Translate-4B weights on %s...", device)
            self._model = AutoModelForCausalLM.from_pretrained(
                self._model_id,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map="auto" if device == "cuda" else None,
                trust_remote_code=False,
            )
            if device == "cpu":
                self._model.to("cpu")
            self._model.eval()
            logger.info("RivaTranslate4BAdapter loaded successfully on %s.", device)
        except Exception as e:
            logger.warning("Riva-Translate-4B load failed (%s). Running in placeholder mode.", e)
            self._model = "FALLBACK_PLACEHOLDER"

    async def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        self._loaded = False

    async def translate(
        self,
        text: str,
        source_language: LanguageCode,
        target_language: LanguageCode,
        context: Optional[TranslationContext] = None,
    ) -> TranslationResult:
        if not self._loaded:
            raise RuntimeError("RivaTranslate4BAdapter not loaded.")
        t0 = time.monotonic()

        if self._model and self._model != "FALLBACK_PLACEHOLDER" and self._tokenizer:
            try:
                import torch
                src_name = "English" if source_language == LanguageCode.EN else "Romanian"
                tgt_name = "Romanian" if target_language == LanguageCode.RO else "English"
                prompt = f"Translate the following text from {src_name} to {tgt_name}:\n{text}\nTranslation:"
                inputs = self._tokenizer(prompt, return_tensors="pt")
                if hasattr(self._model, "device"):
                    inputs = {k: v.to(self._model.device) for k, v in inputs.items()}
                with torch.no_grad():
                    output_tokens = self._model.generate(
                        **inputs,
                        max_new_tokens=self._max_new_tokens,
                        pad_token_id=self._tokenizer.eos_token_id,
                        do_sample=False,
                    )
                translated = self._tokenizer.decode(
                    output_tokens[0][inputs["input_ids"].shape[1]:],
                    skip_special_tokens=True,
                ).strip()
            except Exception as e:
                logger.error("Riva translation inference error: %s", e)
                translated = f"[Translation: {text}]"
        else:
            translated = f"[STUB: {source_language.value}->{target_language.value}: {text}]"

        return TranslationResult(
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
            latency_ms=(time.monotonic() - t0) * 1000.0,
        )

    async def health_check(self) -> bool:
        return self._loaded
