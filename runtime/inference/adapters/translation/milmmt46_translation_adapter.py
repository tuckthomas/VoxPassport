"""Xiaomi MiLMMT-46 local translation adapter.

The adapter uses the model's documented translation prompt and performs inference
locally.  It never sends conference text to an external translation service.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from runtime.inference.protocol import LanguageCode, TranslationContext, TranslationResult

logger = logging.getLogger(__name__)


_LANGUAGE_NAMES = {
    "ar": "Arabic", "az": "Azerbaijani", "bg": "Bulgarian", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "da": "Danish", "de": "German",
    "el": "Greek", "en": "English", "es": "Spanish", "fa": "Persian",
    "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi",
    "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian", "it": "Italian",
    "ja": "Japanese", "kk": "Kazakh", "km": "Khmer", "ko": "Korean",
    "lo": "Lao", "ms": "Malay", "my": "Burmese", "no": "Norwegian",
    "nl": "Dutch", "pl": "Polish", "pt": "Portuguese", "ro": "Romanian",
    "ru": "Russian", "sk": "Slovak", "sl": "Slovenian", "sv": "Swedish",
    "ta": "Tamil", "th": "Thai", "tl": "Tagalog", "tr": "Turkish",
    "ur": "Urdu", "uz": "Uzbek", "vi": "Vietnamese", "yue": "Cantonese",
    "zh": "Chinese (Simplified)", "zh-hant": "Chinese (Traditional)",
}


class MiLMMT46TranslationAdapter:
    """Local Transformers adapter for MiLMMT-46 1B/4B checkpoints."""

    def __init__(
        self,
        model_size: str = "1b",
        model_id: Optional[str] = None,
        max_new_tokens: int = 256,
        device: str = "cuda",
    ) -> None:
        size = str(model_size).lower()
        if size not in ("1b", "4b"):
            raise ValueError(f"model_size must be '1b' or '4b', got {model_size!r}")
        self._model_size = size
        self._model_id = model_id or f"xiaomi-research/MiLMMT-46-{size.upper()}-v1.0"
        self._max_new_tokens = int(max_new_tokens)
        self._device = device
        self._model = None
        self._tokenizer = None
        self._loaded = False
        self._load_error: Optional[str] = None

    async def load(self) -> None:
        if self._loaded and self._model is not None:
            return
        await asyncio.get_running_loop().run_in_executor(None, self._load_blocking)
        if self._model is None or self._tokenizer is None:
            raise RuntimeError(
                "MiLMMT-46 failed to load locally"
                + (f": {self._load_error}" if self._load_error else "")
            )
        self._loaded = True

    def _load_blocking(self) -> None:
        try:
            import sys
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            sys.modules["torchvision"] = None
            project_root = Path(__file__).resolve().parents[4]
            local_candidate = project_root / "models" / f"xiaomi-milmmt-46-{self._model_size}-v1.0"
            model_target = str(local_candidate) if local_candidate.exists() else self._model_id

            self._tokenizer = AutoTokenizer.from_pretrained(model_target, trust_remote_code=False)
            use_cuda = torch.cuda.is_available() and self._device != "cpu"
            dtype = torch.float16 if use_cuda else torch.float32
            self._model = AutoModelForCausalLM.from_pretrained(
                model_target,
                torch_dtype=dtype,
                device_map="auto" if use_cuda else None,
                low_cpu_mem_usage=True,
                trust_remote_code=False,
            )
            if not use_cuda:
                self._model.to("cpu")
            self._model.eval()
            self._load_error = None
            logger.info("Loaded MiLMMT-46-%s locally from %s", self._model_size.upper(), model_target)
        except Exception as exc:
            self._model = None
            self._tokenizer = None
            self._load_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Failed to load MiLMMT-46 locally")

    async def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        self._loaded = False
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    @staticmethod
    def _language_name(code: LanguageCode | str) -> str:
        value = getattr(code, "value", str(code)).lower()
        return _LANGUAGE_NAMES.get(value, value)

    def _translate_blocking(self, text: str, source_language: LanguageCode, target_language: LanguageCode) -> str:
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("MiLMMT-46 is not loaded")

        import torch

        src_name = self._language_name(source_language)
        tgt_name = self._language_name(target_language)
        prompt = (
            f"Translate this from {src_name} to {tgt_name}:\n"
            f"{src_name}: {text}\n"
            f"{tgt_name}:"
        )
        inputs = self._tokenizer(prompt, add_special_tokens=False, return_tensors="pt")
        try:
            model_device = next(self._model.parameters()).device
            inputs = {k: v.to(model_device) for k, v in inputs.items()}
        except Exception:
            pass

        with torch.inference_mode():
            outputs = self._model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=self._max_new_tokens,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        prompt_len = inputs["input_ids"].shape[-1]
        generated = outputs[0][prompt_len:]
        translated = self._tokenizer.decode(generated, skip_special_tokens=True).strip()
        if not translated:
            raise RuntimeError("MiLMMT-46 returned an empty translation")
        return translated

    async def translate(
        self,
        text: str,
        source_language: LanguageCode,
        target_language: LanguageCode,
        context: Optional[TranslationContext] = None,
    ) -> TranslationResult:
        clean_text = str(text).strip()
        if not clean_text:
            return TranslationResult("", source_language, target_language, 0.0)
        if source_language == target_language:
            return TranslationResult(clean_text, source_language, target_language, 0.0)
        if not self._loaded:
            await self.load()

        t0 = time.monotonic()
        translated = await asyncio.get_running_loop().run_in_executor(
            None, self._translate_blocking, clean_text, source_language, target_language
        )
        return TranslationResult(
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
            latency_ms=(time.monotonic() - t0) * 1000.0,
        )

    async def health_check(self) -> bool:
        return self._loaded and self._model is not None and self._tokenizer is not None
