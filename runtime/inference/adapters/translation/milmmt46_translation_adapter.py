"""Xiaomi MiLMMT-46 local translation adapter.

The adapter uses the model's documented translation prompt and performs inference
locally. It never sends conference text to an external translation service.

On GPUs with limited VRAM, translation intentionally stays on CPU so ASR + cloned
TTS can coexist during Voice Studio, Live Studio, and Debug verification. Higher
VRAM systems may keep MiLMMT on CUDA automatically.
"""

from __future__ import annotations

import asyncio
import gc
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

    # Leave enough room for Parakeet, OmniVoice generation activations and the
    # CUDA context on cards such as the RTX 2070 8GB.
    LOW_VRAM_CUTOFF_GB = 10.0

    def __init__(
        self,
        model_size: str = "1b",
        model_id: Optional[str] = None,
        max_new_tokens: int = 256,
        device: str = "auto",
    ) -> None:
        size = str(model_size).lower()
        if size not in ("1b", "4b"):
            raise ValueError(f"model_size must be '1b' or '4b', got {model_size!r}")
        self._model_size = size
        self._model_id = model_id or f"xiaomi-research/MiLMMT-46-{size.upper()}-v1.0"
        self._max_new_tokens = int(max_new_tokens)
        self._device = str(device).lower()
        self._resolved_device = "cpu"
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

    def _choose_device(self, torch) -> str:
        if self._device == "cpu":
            return "cpu"
        if self._device in {"cuda", "cuda:0"}:
            return "cuda" if torch.cuda.is_available() else "cpu"
        if self._device != "auto":
            raise ValueError(f"Unsupported MiLMMT device policy: {self._device!r}")
        if not torch.cuda.is_available():
            return "cpu"
        total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        if total_gb <= self.LOW_VRAM_CUTOFF_GB:
            logger.info(
                "MiLMMT low-VRAM policy: %.1f GB GPU detected; keeping translation on CPU",
                total_gb,
            )
            return "cpu"
        return "cuda"

    def _load_blocking(self) -> None:
        try:
            import sys
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            sys.modules["torchvision"] = None
            project_root = Path(__file__).resolve().parents[4]
            local_candidate = project_root / "models" / f"xiaomi-milmmt-46-{self._model_size}-v1.0"
            model_target = str(local_candidate) if local_candidate.exists() else self._model_id
            resolved = self._choose_device(torch)
            self._resolved_device = resolved

            self._tokenizer = AutoTokenizer.from_pretrained(model_target, trust_remote_code=False)
            if resolved == "cuda":
                self._model = AutoModelForCausalLM.from_pretrained(
                    model_target,
                    torch_dtype=torch.float16,
                    device_map={"": "cuda:0"},
                    low_cpu_mem_usage=True,
                    trust_remote_code=False,
                )
            else:
                self._model = AutoModelForCausalLM.from_pretrained(
                    model_target,
                    torch_dtype=torch.float32,
                    device_map=None,
                    low_cpu_mem_usage=True,
                    trust_remote_code=False,
                )
                self._model.to("cpu")
            self._model.eval()
            self._load_error = None
            logger.info(
                "Loaded MiLMMT-46-%s locally from %s on %s",
                self._model_size.upper(), model_target, resolved,
            )
        except Exception as exc:
            self._model = None
            self._tokenizer = None
            self._load_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Failed to load MiLMMT-46 locally")

    async def unload(self) -> None:
        old_model = self._model
        self._model = None
        self._tokenizer = None
        self._loaded = False
        if old_model is not None:
            del old_model
        gc.collect()
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
        inputs = self._tokenizer(prompt, add_special_tokens=True, return_tensors="pt")
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
                eos_token_id=self._tokenizer.eos_token_id,
                pad_token_id=self._tokenizer.pad_token_id if self._tokenizer.pad_token_id is not None else 0,
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
