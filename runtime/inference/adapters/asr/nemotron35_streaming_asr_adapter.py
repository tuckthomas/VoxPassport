"""
LiveTranslator — Nemotron 3.5 ASR Streaming Adapter
=====================================================
Wraps NVIDIA Nemotron 3.5 ASR Streaming 0.6B for streaming English and Romanian ASR.

Model:  NVIDIA Nemotron 3.5 ASR Streaming 0.6B
Source: https://huggingface.co/nvidia/  (exact model card ID to be verified)
License: OpenMDW-1.1 — verify commercial use terms before distribution
Runtime: NVIDIA NeMo 2.x

Status: STUB — implementation pending model-card verification (Section 46 of plan).
        All interface methods are wired up; inference calls are not yet implemented.

IMPORTANT: Before implementing inference, verify:
  - Exact Hugging Face model ID (Section 46: re-verify before coding)
  - NeMo version compatibility
  - Romanian language support in this checkpoint
  - Streaming chunk size requirements
  - Punctuation/capitalization behavior in Romanian
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import AsyncIterator, Optional

from runtime.inference.adapters.base import AsrAdapter
from runtime.inference.asr_types import AsrConfig, AsrStream
from runtime.inference.protocol import (
    AudioFrame,
    LanguageCode,
    TranscriptEvent,
    TranscriptState,
)

logger = logging.getLogger(__name__)

# Upstream model ID — MUST be verified against the official model card
# before any inference code is written.
_UPSTREAM_MODEL_ID_PLACEHOLDER = "nvidia/nemotron-3.5-asr-streaming-0.6b"
_MODEL_VERIFIED = False  # Set to True after model card re-verification


class _Nemotron35StreamState:
    """Internal state for one open ASR stream."""

    def __init__(self, stream_id: str, config: AsrConfig):
        self.stream_id = stream_id
        self.config = config
        self._event_queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self._closed = False
        self._revision = 0
        # NeMo-specific streaming state — populated after implementation
        self._nemo_stream = None

    def enqueue_event(self, event: TranscriptEvent) -> None:
        self._event_queue.put_nowait(event)

    async def next_event(self, timeout: float = 0.1) -> Optional[TranscriptEvent]:
        try:
            return await asyncio.wait_for(self._event_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None


class Nemotron35StreamingAsrAdapter(AsrAdapter):
    """
    ASR adapter for NVIDIA Nemotron 3.5 ASR Streaming 0.6B.

    Primary candidate for both English (outbound) and Romanian (inbound) ASR.

    Expected characteristics (to be confirmed by bakeoff):
    - Native streaming with partial hypothesis support
    - Romanian support (verify on exact checkpoint)
    - ~0.6B parameters → ~3GB VRAM at fp16
    - Real-time factor < 1.0 on NVIDIA GPU
    """

    ADAPTER_NAME = "Nemotron35StreamingAsrAdapter"
    SUPPORTED_LANGUAGES = [LanguageCode.EN, LanguageCode.RO]  # Verify RO on benchmark
    REQUIRED_SAMPLE_RATE_HZ = 16000

    def __init__(
        self,
        model_id: str = _UPSTREAM_MODEL_ID_PLACEHOLDER,
        device: str = "cuda",
        use_amp: bool = True,
    ):
        if model_id == _UPSTREAM_MODEL_ID_PLACEHOLDER and not _MODEL_VERIFIED:
            logger.warning(
                "Nemotron35StreamingAsrAdapter: upstream model ID has not been "
                "verified against the official model card. See Section 46 of plan."
            )
        self._model_id = model_id
        self._device = device
        self._use_amp = use_amp
        self._model = None
        self._loaded = False
        self._active_streams: dict[str, _Nemotron35StreamState] = {}

    async def load(self) -> None:
        logger.info("Loading Nemotron 3.5 ASR Streaming... model_id=%s", self._model_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_blocking)
        self._loaded = True
        logger.info("Nemotron 3.5 ASR Streaming loaded.")

    def _load_blocking(self) -> None:
        # TODO: Implement after verifying NeMo version and model card.
        # Expected pattern:
        #   import nemo.collections.asr as nemo_asr
        #   self._model = nemo_asr.models.EncDecRNNTBPEModel.from_pretrained(
        #       self._model_id
        #   )
        #   self._model = self._model.to(self._device)
        #   self._model.eval()
        #
        # Stub: log and continue without loading real model.
        logger.warning(
            "Nemotron35StreamingAsrAdapter._load_blocking: STUB — model not loaded. "
            "Implement after model card verification."
        )

    async def unload(self) -> None:
        logger.info("Unloading Nemotron 3.5 ASR Streaming.")
        self._model = None
        self._loaded = False
        self._active_streams.clear()

    async def start_stream(self, config: AsrConfig) -> AsrStream:
        stream_id = str(uuid.uuid4())
        state = _Nemotron35StreamState(stream_id=stream_id, config=config)
        self._active_streams[stream_id] = state
        logger.debug("ASR stream opened: %s (lang=%s)", stream_id, config.language)
        return AsrStream(
            stream_id=stream_id,
            language=config.language,
            sample_rate_hz=config.sample_rate_hz,
            _adapter_state=state,
        )

    async def push_audio(self, stream: AsrStream, frame: AudioFrame) -> None:
        state: _Nemotron35StreamState = stream._adapter_state
        if state._closed:
            raise RuntimeError(f"Stream {stream.stream_id} is already closed.")
        # TODO: Feed frame.data into the NeMo streaming ASR buffer.
        # Stub: no-op until model is loaded.

    async def events(self, stream: AsrStream) -> AsyncIterator[TranscriptEvent]:
        """Yield transcript events from the stream until it is closed."""
        state: _Nemotron35StreamState = stream._adapter_state
        while not state._closed:
            event = await state.next_event(timeout=0.05)
            if event is not None:
                yield event
        # Drain remaining events
        while not state._event_queue.empty():
            yield state._event_queue.get_nowait()

    async def close_stream(self, stream: AsrStream) -> None:
        state: _Nemotron35StreamState = stream._adapter_state
        state._closed = True
        self._active_streams.pop(stream.stream_id, None)
        logger.debug("ASR stream closed: %s", stream.stream_id)

    async def health_check(self) -> bool:
        # Stub returns True only if loaded (no real model to ping yet).
        return self._loaded

    def __repr__(self) -> str:
        return (
            f"Nemotron35StreamingAsrAdapter("
            f"model_id={self._model_id!r}, "
            f"device={self._device!r}, "
            f"loaded={self._loaded})"
        )
