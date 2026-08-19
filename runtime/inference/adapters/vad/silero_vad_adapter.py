"""Silero VAD v6.2.1 adapter.

The model is pinned to the official v6.2.1 torch.hub tag.  VAD remains strictly
speech/non-speech detection: speaker identity, diarization, and language ID are
handled by separate components.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import struct
import uuid

from runtime.inference.adapters.base import VadAdapter
from runtime.inference.protocol import AudioFrame, SampleFormat, VadEvent, VadEventType

logger = logging.getLogger(__name__)


class SileroVadState:
    """Independent VAD state for one audio stream."""

    def __init__(self, stream_id: str, threshold: float = 0.5, model=None):
        self.stream_id = stream_id
        self.threshold = threshold
        self._model = model
        self._in_speech = False
        self._speech_candidate_ms = 0.0
        self._silence_candidate_ms = 0.0
        self._speech_candidate_start_ns: int | None = None
        self._silence_candidate_start_ns: int | None = None


class SileroVadAdapter(VadAdapter):
    """Production VAD backed by the official Silero VAD v6.2.1 model."""

    MODEL_VERSION = "v6.2.1"
    TORCH_HUB_REPOSITORY = f"snakers4/silero-vad:{MODEL_VERSION}"
    CHUNK_SAMPLES_16K = 512
    CHUNK_SAMPLES_8K = 256

    def __init__(
        self,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 150,
        min_silence_duration_ms: int = 300,
    ) -> None:
        self._threshold = float(threshold)
        self._min_speech_duration_ms = max(0, int(min_speech_duration_ms))
        self._min_silence_duration_ms = max(0, int(min_silence_duration_ms))
        self._model = None
        self._get_speech_timestamps = None
        self._loaded = False

    async def load(self) -> None:
        if self._loaded and self._model is not None:
            return
        logger.info("Loading Silero VAD %s", self.MODEL_VERSION)
        await asyncio.get_running_loop().run_in_executor(None, self._load_blocking)
        if self._model is None:
            raise RuntimeError(f"Silero VAD {self.MODEL_VERSION} did not load")
        self._loaded = True

    def _load_blocking(self) -> None:
        try:
            import torch

            model, utils = torch.hub.load(
                repo_or_dir=self.TORCH_HUB_REPOSITORY,
                model="silero_vad",
                force_reload=False,
                onnx=False,
                trust_repo=True,
            )
            self._model = model
            self._get_speech_timestamps = utils[0]
            if hasattr(self._model, "reset_states"):
                self._model.reset_states()
        except Exception as exc:
            self._model = None
            self._get_speech_timestamps = None
            raise RuntimeError(
                f"Could not load pinned Silero VAD {self.MODEL_VERSION}: {exc}"
            ) from exc

    async def unload(self) -> None:
        self._model = None
        self._get_speech_timestamps = None
        self._loaded = False

    def process(self, frame: AudioFrame) -> list[VadEvent]:
        raise NotImplementedError(
            "SileroVadAdapter requires per-stream state; use process_with_state()."
        )

    @staticmethod
    def _frame_duration_ms(frame: AudioFrame) -> float:
        bytes_per_sample = 2 if frame.sample_format == SampleFormat.PCM_S16LE else 4
        channels = max(1, int(frame.channels))
        samples = len(frame.data) / max(1, bytes_per_sample * channels)
        return samples / max(1, int(frame.sample_rate_hz)) * 1000.0

    @staticmethod
    def _audio_tensor(frame: AudioFrame):
        import torch

        if frame.sample_format == SampleFormat.PCM_S16LE:
            n_samples = len(frame.data) // 2
            values = struct.unpack(f"<{n_samples}h", frame.data) if n_samples else ()
            tensor = torch.tensor(values, dtype=torch.float32) / 32768.0
        elif frame.sample_format == SampleFormat.PCM_F32LE:
            n_samples = len(frame.data) // 4
            values = struct.unpack(f"<{n_samples}f", frame.data) if n_samples else ()
            tensor = torch.tensor(values, dtype=torch.float32)
        else:
            raise ValueError(f"Unsupported Silero input format: {frame.sample_format}")

        channels = max(1, int(frame.channels))
        if channels > 1 and tensor.numel() >= channels:
            tensor = tensor[: tensor.numel() - (tensor.numel() % channels)]
            tensor = tensor.reshape(-1, channels).mean(dim=1)

        required = (
            SileroVadAdapter.CHUNK_SAMPLES_8K
            if int(frame.sample_rate_hz) == 8000
            else SileroVadAdapter.CHUNK_SAMPLES_16K
        )
        if tensor.numel() < required:
            tensor = torch.nn.functional.pad(tensor, (0, required - tensor.numel()))
        elif tensor.numel() > required:
            tensor = tensor[:required]
        return tensor

    def process_with_state(self, frame: AudioFrame, state: SileroVadState) -> list[VadEvent]:
        if not self._loaded or self._model is None:
            raise RuntimeError("SileroVadAdapter not loaded. Call load() first.")
        if int(frame.sample_rate_hz) not in (8000, 16000):
            raise ValueError("Silero VAD supports 8 kHz or 16 kHz audio")

        model = state._model or self._model
        try:
            confidence = float(model(self._audio_tensor(frame), int(frame.sample_rate_hz)).item())
        except Exception:
            logger.exception("Silero VAD inference error on stream %s", frame.stream_id)
            return []

        duration_ms = self._frame_duration_ms(frame)
        now_ns = frame.monotonic_timestamp_ns
        events: list[VadEvent] = []

        if confidence >= state.threshold:
            state._silence_candidate_ms = 0.0
            state._silence_candidate_start_ns = None
            if state._in_speech:
                return events

            if state._speech_candidate_ms == 0.0:
                state._speech_candidate_start_ns = now_ns
            state._speech_candidate_ms += duration_ms
            if state._speech_candidate_ms >= self._min_speech_duration_ms:
                state._in_speech = True
                events.append(
                    VadEvent(
                        event_type=VadEventType.SPEECH_START,
                        stream_id=frame.stream_id,
                        monotonic_timestamp_ns=state._speech_candidate_start_ns or now_ns,
                        confidence=confidence,
                    )
                )
                state._speech_candidate_ms = 0.0
                state._speech_candidate_start_ns = None
            return events

        # Non-speech resets an uncommitted speech candidate.
        state._speech_candidate_ms = 0.0
        state._speech_candidate_start_ns = None
        if not state._in_speech:
            events.append(
                VadEvent(
                    event_type=VadEventType.SILENCE,
                    stream_id=frame.stream_id,
                    monotonic_timestamp_ns=now_ns,
                    confidence=1.0 - confidence,
                )
            )
            return events

        if state._silence_candidate_ms == 0.0:
            state._silence_candidate_start_ns = now_ns
        state._silence_candidate_ms += duration_ms
        if state._silence_candidate_ms >= self._min_silence_duration_ms:
            state._in_speech = False
            events.append(
                VadEvent(
                    event_type=VadEventType.SPEECH_END,
                    stream_id=frame.stream_id,
                    monotonic_timestamp_ns=state._silence_candidate_start_ns or now_ns,
                    confidence=1.0 - confidence,
                )
            )
            state._silence_candidate_ms = 0.0
            state._silence_candidate_start_ns = None
        return events

    def create_stream_state(self, stream_id: str | None = None) -> SileroVadState:
        """Create an independent neural state for each simultaneous audio bus."""
        model = None
        if self._model is not None:
            try:
                model = copy.deepcopy(self._model)
                if hasattr(model, "reset_states"):
                    model.reset_states()
            except Exception:
                # Sharing the model is preferable to failing startup, but warn because
                # Silero keeps recurrent state internally.
                logger.warning("Could not clone Silero model state; sharing one model instance")
                model = self._model
        return SileroVadState(
            stream_id=stream_id or str(uuid.uuid4()),
            threshold=self._threshold,
            model=model,
        )

    async def health_check(self) -> bool:
        return self._loaded and self._model is not None

    def __repr__(self) -> str:
        return (
            f"SileroVadAdapter(version={self.MODEL_VERSION!r}, threshold={self._threshold}, "
            f"min_speech_ms={self._min_speech_duration_ms}, "
            f"min_silence_ms={self._min_silence_duration_ms}, loaded={self._loaded})"
        )
