"""XTTS Romanian runtime implementation used only by the generic TTS driver."""

from __future__ import annotations

import gc
import logging
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Iterator

import numpy as np

from runtime.workers.tts_host.drivers.xtts_common import (
    conditioning_cache_key,
    dynamic_max_new_tokens,
    normalize_language,
    prepare_text,
    split_live_clauses,
)

logger = logging.getLogger(__name__)
MODEL_ID = "eduardem/xtts-v2-romanian-v2"


def _patch_romanian_tokenizer() -> None:
    from TTS.tts.layers.xtts import tokenizer as tokenizer_module

    cls = tokenizer_module.VoiceBpeTokenizer
    if getattr(cls, "_voxpassport_romanian_patch", False):
        return
    original = cls.preprocess_text

    def preprocess_text(self, txt, lang):
        base = str(lang).split("-", 1)[0].lower()
        if base == "ro":
            clean = str(txt).translate(str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"}))
            clean = clean.replace('"', "").lower()
            return re.sub(r"\s+", " ", clean).strip()
        return original(self, txt, lang)

    cls.preprocess_text = preprocess_text
    cls._voxpassport_romanian_patch = True


class XttsRomanianRuntime:
    def __init__(self, model_dir: Path, *, device: str = "cuda", cache_size: int = 4) -> None:
        self.model_dir = Path(model_dir)
        self.device = device
        self.cache_size = max(1, int(cache_size))
        self.model = None
        self._lock = threading.RLock()
        self._conditioning_cache: OrderedDict[str, tuple[object, object, str]] = OrderedDict()

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def _ensure_model_files(self) -> None:
        required = (
            "config.json", "model.pth", "dvae.pth", "mel_stats.pth", "vocab.json", "speakers_xtts.pth",
        )
        if all((self.model_dir / name).exists() for name in required):
            return
        from huggingface_hub import snapshot_download

        logger.info("XTTS Romanian checkpoint not present; downloading %s to %s", MODEL_ID, self.model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=MODEL_ID, local_dir=str(self.model_dir))
        missing = [name for name in required if not (self.model_dir / name).exists()]
        if missing:
            raise FileNotFoundError(f"XTTS Romanian download is incomplete; missing: {', '.join(missing)}")

    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            self._ensure_model_files()
            _patch_romanian_tokenizer()
            import torch
            from TTS.tts.configs.xtts_config import XttsConfig
            from TTS.tts.models.xtts import Xtts

            config = XttsConfig()
            config.load_json(str(self.model_dir / "config.json"))
            model = Xtts.init_from_config(config)
            model.load_checkpoint(config, checkpoint_dir=str(self.model_dir), use_deepspeed=False)
            use_cuda = self.device.startswith("cuda") and torch.cuda.is_available()
            model = model.cuda() if use_cuda else model.cpu()
            model.eval()
            model.tokenizer.char_limits["ro"] = 250
            self.device = "cuda" if use_cuda else "cpu"
            self.model = model

    def unload(self) -> None:
        with self._lock:
            self._conditioning_cache.clear()
            old_model = self.model
            self.model = None
            if old_model is not None:
                del old_model
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    def _default_reference(self) -> Path:
        candidates = sorted((self.model_dir / "reference_voices").glob("*.wav"))
        if not candidates:
            raise FileNotFoundError("XTTS stock synthesis requires a bundled reference voice, but none was found")
        return candidates[0]

    def _conditioning(self, canonical_reference: Path, target_reference: Path | None, language: str):
        if self.model is None:
            raise RuntimeError("XTTS Romanian model is not loaded")
        canonical_reference = Path(canonical_reference)
        if not canonical_reference.exists():
            raise FileNotFoundError(f"Canonical voice reference does not exist: {canonical_reference}")
        if target_reference is not None:
            target_reference = Path(target_reference)
            if not target_reference.exists():
                target_reference = None

        key = conditioning_cache_key(canonical_reference, target_reference, language)
        cached = self._conditioning_cache.pop(key, None)
        if cached is not None:
            self._conditioning_cache[key] = cached
            return cached

        canonical_gpt, speaker_embedding = self.model.get_conditioning_latents(
            audio_path=[str(canonical_reference)], gpt_cond_len=6, gpt_cond_chunk_len=6
        )
        mode = "canonical-reference"
        gpt_cond_latent = canonical_gpt
        if target_reference is not None and target_reference.resolve() != canonical_reference.resolve():
            target_gpt, _ = self.model.get_conditioning_latents(
                audio_path=[str(target_reference)], gpt_cond_len=6, gpt_cond_chunk_len=6
            )
            gpt_cond_latent = target_gpt
            mode = "real-speaker+target-language-gpt"

        result = (gpt_cond_latent.detach().cpu(), speaker_embedding.detach().cpu(), mode)
        self._conditioning_cache[key] = result
        while len(self._conditioning_cache) > self.cache_size:
            self._conditioning_cache.popitem(last=False)
        return result

    def stream(
        self,
        *,
        text: str,
        language: str,
        canonical_reference: Path | None,
        target_reference: Path | None = None,
    ) -> Iterator[tuple[bytes, str]]:
        import torch

        language = normalize_language(language)
        clean_text = prepare_text(text, language)
        canonical_reference = Path(canonical_reference) if canonical_reference else self._default_reference()
        with self._lock, torch.inference_mode():
            if self.model is None:
                self.load()
            gpt_cond, speaker_embedding, mode = self._conditioning(
                canonical_reference, target_reference, language
            )
            for clause in split_live_clauses(clean_text):
                max_tokens = dynamic_max_new_tokens(clause) if language == "ro" else 400
                generator = self.model.inference_stream(
                    clause,
                    language,
                    gpt_cond,
                    speaker_embedding,
                    stream_chunk_size=20,
                    overlap_wav_len=1024,
                    temperature=0.3,
                    top_p=0.7,
                    top_k=30,
                    length_penalty=0.8,
                    repetition_penalty=10.0,
                    enable_text_splitting=False,
                    max_new_tokens=max_tokens,
                )
                for tensor in generator:
                    values = tensor.detach().float().cpu().numpy().reshape(-1)
                    if values.size:
                        pcm = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                        if pcm:
                            yield pcm, mode

    def memory_snapshot(self) -> dict:
        try:
            import torch
            if not torch.cuda.is_available():
                return {"cuda": False}
            free, total = torch.cuda.mem_get_info()
            return {
                "cuda": True,
                "allocated_mb": round(torch.cuda.memory_allocated() / 1024**2, 1),
                "reserved_mb": round(torch.cuda.memory_reserved() / 1024**2, 1),
                "free_mb": round(free / 1024**2, 1),
                "total_mb": round(total / 1024**2, 1),
                "conditioning_cache_entries": len(self._conditioning_cache),
            }
        except Exception as exc:
            return {"cuda": None, "error": str(exc)}
