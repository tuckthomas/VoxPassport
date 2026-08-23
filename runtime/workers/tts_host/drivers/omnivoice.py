"""OmniVoice driver for the generic VoxPassport TTS host."""

from __future__ import annotations

import gc
import io
import logging
import sys
from pathlib import Path
from typing import Iterator

from runtime.workers.tts_host.protocol import TtsDriver, TtsDriverRequest

logger = logging.getLogger(__name__)


class OmniVoiceDriver(TtsDriver):
    """Lazy OmniVoice runtime with bounded cloned-speaker conditioning cache."""

    _DEFAULT_QUALITY_STEPS = 32

    def __init__(self, manifest) -> None:
        super().__init__(manifest)
        self._model = None
        self._activated = False
        self._speaker_cache: dict[str, object] = {}

    @staticmethod
    def _release_cuda_cache() -> None:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def load(self) -> None:
        # Keep activation cheap. The model itself loads on first synthesis so the
        # default pipeline does not consume TTS VRAM until audio is requested.
        self._activated = True

    def _ensure_model(self) -> None:
        if not self._activated:
            raise RuntimeError("OmniVoice driver is not loaded")
        if self._model is not None:
            return
        import torch

        project_root = Path(__file__).resolve().parents[4]
        package_dir = str(project_root / "packages")
        if package_dir not in sys.path:
            sys.path.insert(0, package_dir)
        sys.modules["torchvision"] = None
        from omnivoice import OmniVoice

        local_candidate = project_root / "models" / "omnivoice-stock"
        configured = str(self.manifest.driver_options.get("model_path", "")).strip()
        model_target = str(local_candidate) if local_candidate.exists() else (configured or "k2-fsa/OmniVoice")
        use_cuda = torch.cuda.is_available()
        if use_cuda:
            self._release_cuda_cache()
        self._model = OmniVoice.from_pretrained(
            model_target,
            device_map="cuda:0" if use_cuda else "cpu",
            dtype=torch.float16 if use_cuda else torch.float32,
        )
        logger.info("Loaded OmniVoice TTS driver on %s", "cuda:0" if use_cuda else "cpu")

    def unload(self) -> None:
        self._speaker_cache.clear()
        old_model = self._model
        self._model = None
        self._activated = False
        if old_model is not None:
            del old_model
        self._release_cuda_cache()

    @staticmethod
    def _cache_key(reference: Path, transcript: str) -> str:
        return f"{reference.resolve()}::{transcript.strip() or '<auto-transcribe>'}"

    def _generate_float_audio(self, request: TtsDriverRequest):
        import numpy as np
        import torch
        from omnivoice import OmniVoiceGenerationConfig

        self._ensure_model()
        clean = str(request.text).strip()
        if not clean:
            raise ValueError("Target TTS text must not be empty")

        cfg = OmniVoiceGenerationConfig(
            num_step=self._DEFAULT_QUALITY_STEPS,
            denoise=True,
            preprocess_prompt=True,
            postprocess_output=True,
        )
        prompt = None
        if request.reference_audio is not None:
            reference = Path(request.reference_audio)
            if not reference.exists():
                raise FileNotFoundError(f"Reference audio does not exist: {reference}")
            key = self._cache_key(reference, request.reference_text)
            prompt = self._speaker_cache.get(key)
            if prompt is None:
                # One retained prompt prevents unused profiles from accumulating
                # tensors while still avoiding per-utterance conditioning work.
                self._speaker_cache.clear()
                prompt = self._model.create_voice_clone_prompt(
                    ref_audio=str(reference),
                    ref_text=request.reference_text.strip() or None,
                    preprocess_prompt=True,
                )
                self._speaker_cache[key] = prompt

        with torch.inference_mode():
            result = self._model.generate(
                text=clean,
                language=request.language or None,
                voice_clone_prompt=prompt,
                generation_config=cfg,
                normalize_text=True,
            )
        if not result:
            raise RuntimeError("OmniVoice returned no audio")
        audio = np.asarray(result[0], dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=-1 if audio.shape[-1] < audio.shape[0] else 0)
        return np.ascontiguousarray(audio.reshape(-1), dtype=np.float32)

    def synthesize_pcm(self, request: TtsDriverRequest) -> Iterator[bytes]:
        import numpy as np

        try:
            audio = self._generate_float_audio(request)
        except Exception as exc:
            if "out of memory" in str(exc).lower():
                self._release_cuda_cache()
            raise
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
        chunk_samples = max(1, int(self.manifest.native_sample_rate_hz * 0.10))
        for offset in range(0, pcm.size, chunk_samples):
            yield pcm[offset : offset + chunk_samples].tobytes()

    def synthesize_wav(self, request: TtsDriverRequest) -> bytes:
        import soundfile as sf

        audio = self._generate_float_audio(request)
        output = io.BytesIO()
        sf.write(output, audio, self.manifest.native_sample_rate_hz, format="WAV")
        return output.getvalue()

    def health_check(self) -> bool:
        return self._activated

    def metrics(self) -> dict:
        result = {"loaded": self._activated, "weights_loaded": self._model is not None}
        try:
            import torch
            if torch.cuda.is_available():
                result.update({
                    "allocated_mb": round(torch.cuda.memory_allocated() / 1024**2, 1),
                    "reserved_mb": round(torch.cuda.memory_reserved() / 1024**2, 1),
                })
        except Exception:
            pass
        return result
