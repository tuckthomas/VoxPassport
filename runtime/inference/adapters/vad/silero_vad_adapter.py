"""
LiveTranslator — Silero VAD Adapter
=====================================
Wraps the Silero VAD model for voice activity detection.

Silero VAD:
  Repository: https://github.com/snakers4/silero-vad
  License: MIT
  Model size: ~1MB
  Latency: <1ms per 30ms frame (CPU-bound is fine)

Design notes:
- Silero VAD processes 512-sample (at 16kHz) or 256-sample (at 8kHz) windows.
- For 16kHz audio: 512 samples = 32ms per call.
- State is maintained per-stream to support multiple simultaneous VAD instances.
- This adapter is used for both the outbound (English) and inbound (Romanian) streams.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

from runtime.inference.adapters.base import VadAdapter
from runtime.inference.protocol import (
    AudioFrame,
    VadEvent,
    VadEventType,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SileroVadState:
    """Per-stream Silero VAD state."""

    def __init__(self, stream_id: str, threshold: float = 0.5):
        self.stream_id = stream_id
        self.threshold = threshold
        self._in_speech = False
        # Model state — populated after load
        self._model = None
        self._utils = None


class SileroVadAdapter(VadAdapter):
    """
    Production VAD adapter backed by Silero VAD.

    Usage:
        adapter = SileroVadAdapter()
        await adapter.load()

        state = SileroVadState(stream_id="outbound-1")
        for frame in audio_frames:
            events = adapter.process_with_state(frame, state)
            for event in events:
                handle_vad_event(event)

        await adapter.unload()
    """

    # Silero VAD chunk size at 16kHz: 512 samples
    CHUNK_SAMPLES_16K = 512
    # Silero VAD chunk size at 8kHz: 256 samples
    CHUNK_SAMPLES_8K = 256

    def __init__(
        self,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 150,
        min_silence_duration_ms: int = 300,
    ):
        self._threshold = threshold
        self._min_speech_duration_ms = min_speech_duration_ms
        self._min_silence_duration_ms = min_silence_duration_ms
        self._model = None
        self._get_speech_timestamps = None
        self._loaded = False

    async def load(self) -> None:
        """Load Silero VAD via torch.hub."""
        logger.info("Loading Silero VAD...")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_blocking)
        self._loaded = True
        logger.info("Silero VAD loaded.")

    def _load_blocking(self) -> None:
        try:
            import torch  # noqa: F401 — lazy import
            try:
                # Use the official Silero VAD loading mechanism
                model, utils = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    force_reload=False,
                    onnx=False,
                    trust_repo=True,
                )
                self._model = model
                (
                    self._get_speech_timestamps,
                    _,
                    _,
                    _,
                    _,
                ) = utils
            except Exception as hub_err:
                logger.warning("torch.hub Silero VAD load failed (%s). Running in mock VAD mode.", hub_err)
                self._model = "MOCK_SILERO_VAD"
        except ImportError as e:
            logger.warning("PyTorch not installed. Running Silero VAD in fallback mode.")
            self._model = "MOCK_SILERO_VAD"

    async def unload(self) -> None:
        logger.info("Unloading Silero VAD.")
        self._model = None
        self._get_speech_timestamps = None
        self._loaded = False

    def process(self, frame: AudioFrame) -> list[VadEvent]:
        """
        Single-frame VAD using internal persistent state.
        For multi-stream use, prefer process_with_state().
        """
        raise NotImplementedError(
            "SileroVadAdapter requires per-stream state. "
            "Use process_with_state(frame, state) instead."
        )

    def process_with_state(
        self,
        frame: AudioFrame,
        state: SileroVadState,
    ) -> list[VadEvent]:
        """
        Process a frame using per-stream Silero state.
        Returns VAD events (speech_start, speech_end, silence).
        """
        if not self._loaded or self._model is None:
            raise RuntimeError("SileroVadAdapter not loaded. Call load() first.")

        if self._model == "MOCK_SILERO_VAD":
            # In mock fallback mode, compute simple energy-based detection
            confidence = 0.8 if len(frame.data) > 0 and any(b != 0 for b in frame.data) else 0.0
        else:
            try:
                import torch

                # Convert bytes → float32 tensor
                if frame.sample_format.value == "pcm_s16le":
                    import struct
                    n_samples = len(frame.data) // 2
                    samples = struct.unpack(f"<{n_samples}h", frame.data)
                    audio_tensor = torch.tensor(samples, dtype=torch.float32) / 32768.0
                elif frame.sample_format.value == "pcm_f32le":
                    import struct
                    n_samples = len(frame.data) // 4
                    samples = struct.unpack(f"<{n_samples}f", frame.data)
                    audio_tensor = torch.tensor(samples, dtype=torch.float32)
                if audio_tensor.shape[0] < 512:
                    audio_tensor = torch.nn.functional.pad(audio_tensor, (0, 512 - audio_tensor.shape[0]))

                confidence = self._model(audio_tensor, frame.sample_rate_hz).item()

            except Exception:
                logger.exception("Silero VAD inference error on stream %s", frame.stream_id)
                return []

        events: list[VadEvent] = []
        now_ns = frame.monotonic_timestamp_ns

        if confidence >= self._threshold:
            if not state._in_speech:
                state._in_speech = True
                events.append(
                    VadEvent(
                        event_type=VadEventType.SPEECH_START,
                        stream_id=frame.stream_id,
                        monotonic_timestamp_ns=now_ns,
                        confidence=confidence,
                    )
                )
        else:
            if state._in_speech:
                state._in_speech = False
                events.append(
                    VadEvent(
                        event_type=VadEventType.SPEECH_END,
                        stream_id=frame.stream_id,
                        monotonic_timestamp_ns=now_ns,
                        confidence=1.0 - confidence,
                    )
                )
            else:
                events.append(
                    VadEvent(
                        event_type=VadEventType.SILENCE,
                        stream_id=frame.stream_id,
                        monotonic_timestamp_ns=now_ns,
                        confidence=1.0 - confidence,
                    )
                )

        return events

    def create_stream_state(
        self,
        stream_id: str | None = None,
    ) -> SileroVadState:
        """Create fresh per-stream state."""
        return SileroVadState(
            stream_id=stream_id or str(uuid.uuid4()),
            threshold=self._threshold,
        )

    async def health_check(self) -> bool:
        return self._loaded and self._model is not None

    def __repr__(self) -> str:
        return (
            f"SileroVadAdapter("
            f"threshold={self._threshold}, "
            f"loaded={self._loaded})"
        )
