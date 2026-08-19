"""Optional inbound NVIDIA Streaming Sortformer 4spk v2.1 sidecar.

This adapter is deliberately not on the critical ASR path. Audio is copied into
a rolling buffer and diarization is scheduled on a background task; ASR,
translation, and TTS never wait for a speaker label. On low-VRAM systems the
sidecar runs on CPU so it cannot crowd cloned TTS off the GPU during Live Studio
or pre-conference debugging.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import math
import re
import time
from pathlib import Path

import numpy as np

from runtime.inference.protocol import AudioFrame, SampleFormat

logger = logging.getLogger(__name__)


class SortformerStreamingDiarizationAdapter:
    MODEL_ID = "nvidia/diar_streaming_sortformer_4spk-v2.1"
    REQUIRED_SAMPLE_RATE_HZ = 16000
    MAX_SPEAKERS = 4
    LOW_VRAM_CUTOFF_GB = 12.0

    # NVIDIA's published low-input-buffer-latency configuration.
    CHUNK_LEN = 6
    CHUNK_RIGHT_CONTEXT = 7
    FIFO_LEN = 188
    SPKCACHE_UPDATE_PERIOD = 144
    SPKCACHE_LEN = 188

    def __init__(
        self,
        model_path: str | Path,
        device: str = "auto",
        inference_interval_s: float = 1.04,
        rolling_context_s: float = 12.0,
    ) -> None:
        self.model_path = Path(model_path)
        self.device = str(device).lower()
        self.resolved_device = "cpu"
        self.inference_interval_s = max(1.04, float(inference_interval_s))
        self.rolling_context_s = max(self.inference_interval_s, float(rolling_context_s))
        self._model = None
        self._loaded = False
        self._pcm = bytearray()
        self._lock = asyncio.Lock()
        self._infer_task: asyncio.Task | None = None
        self._bytes_since_infer = 0
        self._latest: dict | None = None
        self._latest_monotonic = 0.0

    def _checkpoint_path(self) -> Path:
        if self.model_path.is_file() and self.model_path.suffix == ".nemo":
            return self.model_path
        matches = sorted(self.model_path.glob("*.nemo")) if self.model_path.exists() else []
        if not matches:
            raise FileNotFoundError(
                f"Sortformer checkpoint not found under {self.model_path}. "
                "Download nvidia/diar_streaming_sortformer_4spk-v2.1 from the Model Hub first."
            )
        return matches[0]

    async def load(self) -> None:
        if self._loaded and self._model is not None:
            return
        await asyncio.get_running_loop().run_in_executor(None, self._load_blocking)
        if self._model is None:
            raise RuntimeError("Streaming Sortformer failed to load")
        self._loaded = True

    def _choose_device(self, torch) -> str:
        if self.device == "cpu":
            return "cpu"
        if self.device in {"cuda", "cuda:0"}:
            return "cuda" if torch.cuda.is_available() else "cpu"
        if self.device != "auto":
            raise ValueError(f"Unsupported Sortformer device policy: {self.device!r}")
        if not torch.cuda.is_available():
            return "cpu"
        total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        if total_gb <= self.LOW_VRAM_CUTOFF_GB:
            logger.info(
                "Sortformer low-VRAM policy: %.1f GB GPU detected; diarization will run on CPU",
                total_gb,
            )
            return "cpu"
        return "cuda"

    def _load_blocking(self) -> None:
        try:
            import torch
            from nemo.collections.asr.models import SortformerEncLabelModel
        except ImportError as exc:
            raise RuntimeError(
                "Streaming Sortformer requires NVIDIA NeMo ASR. Install the NeMo ASR "
                "runtime before enabling diarization."
            ) from exc

        checkpoint = self._checkpoint_path()
        self.resolved_device = self._choose_device(torch)
        map_location = "cuda" if self.resolved_device == "cuda" else "cpu"
        model = SortformerEncLabelModel.restore_from(
            restore_path=str(checkpoint), map_location=map_location, strict=False
        )
        model.eval()
        modules = model.sortformer_modules
        modules.chunk_len = self.CHUNK_LEN
        modules.chunk_right_context = self.CHUNK_RIGHT_CONTEXT
        modules.fifo_len = self.FIFO_LEN
        modules.spkcache_update_period = self.SPKCACHE_UPDATE_PERIOD
        modules.spkcache_len = self.SPKCACHE_LEN
        modules._check_streaming_parameters()
        self._model = model
        logger.info("Loaded Streaming Sortformer sidecar from %s on %s", checkpoint, self.resolved_device)

    async def unload(self) -> None:
        if self._infer_task and not self._infer_task.done():
            self._infer_task.cancel()
            try:
                await self._infer_task
            except asyncio.CancelledError:
                pass
        self._infer_task = None
        old_model = self._model
        self._model = None
        self._loaded = False
        self._pcm.clear()
        self._bytes_since_infer = 0
        self._latest = None
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
    def _frame_to_float32(frame: AudioFrame) -> np.ndarray:
        if frame.sample_format == SampleFormat.PCM_S16LE:
            audio = np.frombuffer(frame.data, dtype="<i2").astype(np.float32) / 32768.0
        elif frame.sample_format == SampleFormat.PCM_F32LE:
            audio = np.frombuffer(frame.data, dtype="<f4").astype(np.float32, copy=False)
        else:
            raise ValueError(f"Unsupported diarization input format: {frame.sample_format}")

        channels = max(1, int(frame.channels))
        if channels > 1 and audio.size >= channels:
            usable = audio[: audio.size - (audio.size % channels)]
            audio = usable.reshape(-1, channels).mean(axis=1)

        if int(frame.sample_rate_hz) != SortformerStreamingDiarizationAdapter.REQUIRED_SAMPLE_RATE_HZ:
            from scipy.signal import resample_poly
            source_rate = int(frame.sample_rate_hz)
            divisor = math.gcd(source_rate, SortformerStreamingDiarizationAdapter.REQUIRED_SAMPLE_RATE_HZ)
            audio = resample_poly(
                audio,
                SortformerStreamingDiarizationAdapter.REQUIRED_SAMPLE_RATE_HZ // divisor,
                source_rate // divisor,
            ).astype(np.float32, copy=False)
        return np.asarray(audio, dtype=np.float32)

    async def push_audio(self, frame: AudioFrame) -> None:
        """Queue audio for diarization without awaiting neural inference."""
        if not self._loaded or self._model is None:
            return
        audio = self._frame_to_float32(frame)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        bytes_per_second = self.REQUIRED_SAMPLE_RATE_HZ * 2
        async with self._lock:
            self._pcm.extend(pcm)
            max_bytes = int(bytes_per_second * self.rolling_context_s)
            if len(self._pcm) > max_bytes:
                del self._pcm[:-max_bytes]
            self._bytes_since_infer += len(pcm)
            due = self._bytes_since_infer >= int(bytes_per_second * self.inference_interval_s)
            if due and (self._infer_task is None or self._infer_task.done()):
                snapshot = bytes(self._pcm)
                self._bytes_since_infer = 0
                self._infer_task = asyncio.create_task(self._infer_snapshot(snapshot))

    async def _infer_snapshot(self, pcm: bytes) -> None:
        try:
            segments = await asyncio.get_running_loop().run_in_executor(
                None, self._diarize_blocking, pcm
            )
            latest = self._latest_segment(segments)
            if latest:
                self._latest = latest
                self._latest_monotonic = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Parallel Sortformer inference failed", exc_info=True)

    def _diarize_blocking(self, pcm: bytes):
        if self._model is None or not pcm:
            return []
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        predicted = self._model.diarize(audio=[audio], batch_size=1, sample_rate=16000)
        if isinstance(predicted, tuple):
            predicted = predicted[0]
        if isinstance(predicted, list) and predicted:
            return predicted[0]
        return []

    @staticmethod
    def _parse_segment(segment) -> tuple[float, float, int] | None:
        if isinstance(segment, (tuple, list)) and len(segment) >= 3:
            try:
                return float(segment[0]), float(segment[1]), int(segment[2])
            except (TypeError, ValueError):
                return None
        text = str(segment)
        numbers = re.findall(r"-?\d+(?:\.\d+)?", text)
        if len(numbers) < 3:
            return None
        try:
            return float(numbers[0]), float(numbers[1]), int(float(numbers[2]))
        except ValueError:
            return None

    @classmethod
    def _latest_segment(cls, segments) -> dict | None:
        parsed = [value for segment in (segments or []) if (value := cls._parse_segment(segment))]
        if not parsed:
            return None
        start_s, end_s, speaker_index = max(parsed, key=lambda item: item[1])
        if speaker_index < 0 or speaker_index >= cls.MAX_SPEAKERS:
            return None
        return {
            "speaker_index": speaker_index,
            "speaker_label": f"Speaker {speaker_index + 1}",
            "speaker_start_s": start_s,
            "speaker_end_s": end_s,
            "diarization_model": cls.MODEL_ID,
        }

    def latest_speaker(self, max_age_s: float = 3.0) -> dict | None:
        """Return a recent anonymous speaker cluster label, never a person identity."""
        if not self._latest or time.monotonic() - self._latest_monotonic > max_age_s:
            return None
        return dict(self._latest)

    async def health_check(self) -> bool:
        return self._loaded and self._model is not None
