"""Streaming adapter for NVIDIA Parakeet TDT 0.6B v3.

The Hugging Face/Transformers checkpoint is used locally.  Audio is accumulated
per stream and re-decoded at short intervals so the rest of VoxPassport receives
revisionable partial hypotheses.  VAD endpoints request one final decode and
reset the rolling utterance buffer.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import numpy as np

from runtime.inference.adapters.base import AsrAdapter
from runtime.inference.asr_types import AsrConfig, AsrStream
from runtime.inference.protocol import AudioFrame, LanguageCode, SampleFormat, TranscriptEvent, TranscriptState

logger = logging.getLogger(__name__)

_UPSTREAM_MODEL_ID = "nvidia/parakeet-tdt-0.6b-v3"


class _ParakeetStreamState:
    def __init__(self, stream_id: str, config: AsrConfig) -> None:
        self.stream_id = stream_id
        self.config = config
        self.event_queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self.closed = False
        self.revision = 0
        self.utterance_id = str(uuid.uuid4())
        self.pcm = bytearray()
        self.last_inferred_bytes = 0
        self.infer_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()


class ParakeetTdtV3AsrAdapter(AsrAdapter):
    ADAPTER_NAME = "ParakeetTdtV3AsrAdapter"
    REQUIRED_SAMPLE_RATE_HZ = 16000

    def __init__(self, model_id: str = _UPSTREAM_MODEL_ID, device: str = "cuda") -> None:
        self._model_id = model_id
        self._device = device
        self._pipe = None
        self._loaded = False
        self._active_streams: dict[str, _ParakeetStreamState] = {}
        self._decode_interval_s = 0.75
        self._max_context_s = 12.0

    async def load(self) -> None:
        if self._loaded and self._pipe is not None:
            return
        await asyncio.get_running_loop().run_in_executor(None, self._load_blocking)
        if self._pipe is None:
            raise RuntimeError("Parakeet TDT failed to load locally")
        self._loaded = True

    def _load_blocking(self) -> None:
        try:
            import torch
            from transformers import pipeline

            project_root = Path(__file__).resolve().parents[4]
            local_candidate = project_root / "models" / "nvidia-parakeet-tdt-0.6b-v3"
            model_target = str(local_candidate) if local_candidate.exists() else self._model_id
            device = 0 if torch.cuda.is_available() and self._device != "cpu" else -1
            kwargs = {"device": device}
            if device >= 0:
                kwargs["torch_dtype"] = torch.float16
            self._pipe = pipeline("automatic-speech-recognition", model=model_target, **kwargs)
            logger.info("Loaded Parakeet TDT locally from %s", model_target)
        except Exception:
            self._pipe = None
            logger.exception("Failed to load Parakeet TDT")

    async def unload(self) -> None:
        for state in list(self._active_streams.values()):
            state.closed = True
            if state.infer_task:
                state.infer_task.cancel()
        self._active_streams.clear()
        self._pipe = None
        self._loaded = False
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    async def start_stream(self, config: AsrConfig) -> AsrStream:
        if not self._loaded:
            await self.load()
        stream_id = str(uuid.uuid4())
        state = _ParakeetStreamState(stream_id, config)
        self._active_streams[stream_id] = state
        return AsrStream(
            stream_id=stream_id,
            language=config.language,
            sample_rate_hz=config.sample_rate_hz,
            _adapter_state=state,
        )

    @staticmethod
    def _frame_to_s16(frame: AudioFrame) -> bytes:
        if frame.sample_format == SampleFormat.PCM_S16LE:
            return frame.data
        if frame.sample_format == SampleFormat.PCM_F32LE:
            values = np.frombuffer(frame.data, dtype="<f4")
            return (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        raise ValueError(f"Unsupported ASR input format: {frame.sample_format}")

    async def push_audio(self, stream: AsrStream, frame: AudioFrame) -> None:
        state: _ParakeetStreamState = stream._adapter_state
        if state.closed:
            return
        pcm = self._frame_to_s16(frame)
        async with state.lock:
            state.pcm.extend(pcm)
            bytes_per_second = max(1, state.config.sample_rate_hz * 2 * state.config.channels)
            due = len(state.pcm) - state.last_inferred_bytes >= int(bytes_per_second * self._decode_interval_s)
            if due and (state.infer_task is None or state.infer_task.done()):
                state.last_inferred_bytes = len(state.pcm)
                state.infer_task = asyncio.create_task(self._decode_state(state, final=False))

    def _transcribe_blocking(self, pcm: bytes, sample_rate: int) -> str:
        if self._pipe is None or not pcm:
            return ""
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        result = self._pipe({"array": audio, "sampling_rate": int(sample_rate)})
        if isinstance(result, dict):
            return str(result.get("text", "")).strip()
        return str(result or "").strip()

    async def _decode_state(self, state: _ParakeetStreamState, final: bool) -> None:
        async with state.lock:
            if state.closed and not final:
                return
            bytes_per_second = max(1, state.config.sample_rate_hz * 2 * state.config.channels)
            max_bytes = int(bytes_per_second * self._max_context_s)
            pcm = bytes(state.pcm[-max_bytes:])
            utterance_id = state.utterance_id
            state.revision += 1
            revision = state.revision

        text = await asyncio.get_running_loop().run_in_executor(
            None, self._transcribe_blocking, pcm, state.config.sample_rate_hz
        )
        if not text and not final:
            return
        try:
            language = LanguageCode(state.config.language)
        except ValueError:
            language = LanguageCode.EN
        await state.event_queue.put(
            TranscriptEvent(
                utterance_id=utterance_id,
                revision=revision,
                source_language=language,
                text=text,
                state=TranscriptState.FINAL if final else TranscriptState.PARTIAL,
            )
        )

    async def endpoint(self, stream: AsrStream) -> str:
        """Force a final decode for the current VAD utterance and rotate buffers."""
        state: _ParakeetStreamState = stream._adapter_state
        if state.infer_task and not state.infer_task.done():
            try:
                await state.infer_task
            except asyncio.CancelledError:
                pass
        current_id = state.utterance_id
        await self._decode_state(state, final=True)
        async with state.lock:
            state.pcm.clear()
            state.last_inferred_bytes = 0
            state.revision = 0
            state.utterance_id = str(uuid.uuid4())
            state.infer_task = None
        return current_id

    async def events(self, stream: AsrStream) -> AsyncIterator[TranscriptEvent]:
        state: _ParakeetStreamState = stream._adapter_state
        while not state.closed:
            try:
                yield await asyncio.wait_for(state.event_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

    async def close_stream(self, stream: AsrStream) -> None:
        state: _ParakeetStreamState = stream._adapter_state
        if state.pcm:
            try:
                await self.endpoint(stream)
            except Exception:
                logger.exception("Final Parakeet decode failed during stream close")
        state.closed = True
        if state.infer_task:
            state.infer_task.cancel()
        self._active_streams.pop(stream.stream_id, None)

    async def health_check(self) -> bool:
        return self._loaded and self._pipe is not None
