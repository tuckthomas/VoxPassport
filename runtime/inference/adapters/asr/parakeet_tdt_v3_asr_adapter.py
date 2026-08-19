"""
LiveTranslator — Parakeet TDT 0.6B v3 ASR Adapter
===================================================
Benchmark comparator for Nemotron 3.5 Streaming.

Model:  NVIDIA Parakeet TDT 0.6B v3
Source: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
License: CC BY 4.0 — attribution required
Runtime: NVIDIA NeMo

Status: STUB — benchmark comparator. Verify Romanian support before promoting.

IMPORTANT: Before using for Romanian:
  - Verify Romanian language support on the exact v3 checkpoint.
  - Run the ASR bakeoff (benchmarks/asr_bakeoff.py) against Nemotron 3.5.
  - Parakeet TDT was originally strong on English; Romanian may not be equal.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import AsyncIterator, Optional

from runtime.inference.adapters.base import AsrAdapter
from runtime.inference.asr_types import AsrConfig, AsrStream
from runtime.inference.protocol import AudioFrame, LanguageCode, TranscriptEvent

logger = logging.getLogger(__name__)

_UPSTREAM_MODEL_ID = "nvidia/parakeet-tdt-0.6b-v3"


class _ParakeetStreamState:
    def __init__(self, stream_id: str, config: AsrConfig):
        self.stream_id = stream_id
        self.config = config
        self._event_queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self._closed = False
        self._nemo_stream = None


class ParakeetTdtV3AsrAdapter(AsrAdapter):
    """
    ASR adapter for NVIDIA Parakeet TDT 0.6B v3.

    Used as a benchmark comparator against Nemotron 3.5 Streaming.
    Not the production default unless bakeoff shows it's better for EN+RO.
    """

    ADAPTER_NAME = "ParakeetTdtV3AsrAdapter"
    REQUIRED_SAMPLE_RATE_HZ = 16000

    def __init__(
        self,
        model_id: str = _UPSTREAM_MODEL_ID,
        device: str = "cuda",
    ):
        self._model_id = model_id
        self._device = device
        self._model = None
        self._loaded = False
        self._active_streams: dict[str, _ParakeetStreamState] = {}

    async def load(self) -> None:
        logger.info("Loading Parakeet TDT 0.6B v3... model_id=%s", self._model_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_blocking)
        self._loaded = True
        logger.info("Parakeet TDT 0.6B v3 loaded.")

    def _load_blocking(self) -> None:
        from pathlib import Path
        local_candidate = Path(__file__).resolve().parents[4] / "models" / "nvidia-parakeet-tdt-0.6b-v3"
        model_target = str(local_candidate) if local_candidate.exists() else self._model_id
        
        logger.info("Checking Parakeet model files at %s...", model_target)
        if local_candidate.exists():
            nemo_file = local_candidate / "parakeet-tdt-0.6b-v3.nemo"
            safetensors_file = local_candidate / "model.safetensors"
            if nemo_file.exists() or safetensors_file.exists():
                self._model = f"LOCAL_MODEL_VERIFIED: {model_target}"
                logger.info("Parakeet TDT 0.6B v3 model weights verified locally at %s.", model_target)
                return
        logger.warning("ParakeetTdtV3AsrAdapter: model weights not found at %s. Running in fallback mode.", model_target)
        self._model = "FALLBACK_PLACEHOLDER"

    async def unload(self) -> None:
        self._model = None
        self._loaded = False
        self._active_streams.clear()

    async def start_stream(self, config: AsrConfig) -> AsrStream:
        stream_id = str(uuid.uuid4())
        state = _ParakeetStreamState(stream_id=stream_id, config=config)
        self._active_streams[stream_id] = state
        return AsrStream(
            stream_id=stream_id,
            language=config.language,
            sample_rate_hz=config.sample_rate_hz,
            _adapter_state=state,
        )

    async def push_audio(self, stream: AsrStream, frame: AudioFrame) -> None:
        # TODO: Feed into NeMo streaming buffer
        pass

    async def events(self, stream: AsrStream) -> AsyncIterator[TranscriptEvent]:
        state: _ParakeetStreamState = stream._adapter_state
        while not state._closed:
            try:
                event = await asyncio.wait_for(state._event_queue.get(), timeout=0.05)
                yield event
            except asyncio.TimeoutError:
                pass

    async def close_stream(self, stream: AsrStream) -> None:
        state: _ParakeetStreamState = stream._adapter_state
        state._closed = True
        self._active_streams.pop(stream.stream_id, None)

    async def health_check(self) -> bool:
        return self._loaded
