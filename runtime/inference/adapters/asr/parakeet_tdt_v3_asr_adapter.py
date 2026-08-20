"""Streaming adapter for NVIDIA Parakeet TDT 0.6B v3.

The Hugging Face/Transformers checkpoint is used locally. Multiple logical ASR
adapters/streams share one physical Parakeet model so bidirectional translation
does not duplicate the same 0.6B model in VRAM. Inference is serialized through
the shared pipeline because Transformers pipelines are not guaranteed to be
thread-safe when two conference directions speak at once.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import numpy as np

from runtime.inference.adapters.base import AsrAdapter
from runtime.inference.asr_types import AsrConfig, AsrStream
from runtime.inference.gpu_inference_coordinator import heavy_gpu_inference
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

    # English and Romanian are streams of the same multilingual model. Keep one
    # physical Transformers pipeline per process rather than one model per slot.
    _shared_lock = threading.Lock()
    _shared_inference_lock = threading.Lock()
    _shared_pipe = None
    _shared_key: tuple[str, int] | None = None
    _shared_refcount = 0

    def __init__(self, model_id: str = _UPSTREAM_MODEL_ID, device: str = "cuda") -> None:
        self._model_id = model_id
        self._device = device
        self._pipe = None
        self._loaded = False
        self._shared_ref_acquired = False
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
            key = (model_target, device)
            cls = type(self)

            with cls._shared_lock:
                if cls._shared_pipe is not None:
                    if cls._shared_key != key:
                        raise RuntimeError(
                            "A shared Parakeet model is already resident with a different model/device. "
                            "Unload the active ASR model before switching variants."
                        )
                    cls._shared_refcount += 1
                    self._pipe = cls._shared_pipe
                    self._shared_ref_acquired = True
                    logger.info(
                        "Reusing shared Parakeet TDT model (%d logical ASR adapters)",
                        cls._shared_refcount,
                    )
                    return

                kwargs = {"device": device}
                if device >= 0:
                    kwargs["torch_dtype"] = torch.float16
                pipe = pipeline("automatic-speech-recognition", model=model_target, **kwargs)
                cls._shared_pipe = pipe
                cls._shared_key = key
                cls._shared_refcount = 1
                self._pipe = pipe
                self._shared_ref_acquired = True
                logger.info("Loaded one shared Parakeet TDT model from %s", model_target)
        except Exception:
            self._pipe = None
            self._shared_ref_acquired = False
            logger.exception("Failed to load Parakeet TDT")

    async def unload(self) -> None:
        for state in list(self._active_streams.values()):
            state.closed = True
            if state.infer_task:
                state.infer_task.cancel()
        self._active_streams.clear()

        released_pipe = None
        cls = type(self)
        with cls._shared_lock:
            if self._shared_ref_acquired:
                cls._shared_refcount = max(0, cls._shared_refcount - 1)
                self._shared_ref_acquired = False
                if cls._shared_refcount == 0:
                    released_pipe = cls._shared_pipe
                    cls._shared_pipe = None
                    cls._shared_key = None
            self._pipe = None
            self._loaded = False

        if released_pipe is not None:
            del released_pipe
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            logger.info("Released shared Parakeet TDT model")

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

    def _transcribe_result_blocking(self, pcm: bytes, sample_rate: int) -> tuple[str, str | None]:
        if self._pipe is None or not pcm:
            return "", None
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        with heavy_gpu_inference(), type(self)._shared_inference_lock:
            result = self._pipe({"array": audio, "sampling_rate": int(sample_rate)})
        if isinstance(result, dict):
            text = str(result.get("text", "")).strip()
            detected = result.get("language") or result.get("lang")
            return text, (str(detected).lower().strip() if detected else None)
        return str(result or "").strip(), None

    def _transcribe_blocking(self, pcm: bytes, sample_rate: int) -> str:
        """Compatibility helper used by verification tools."""
        return self._transcribe_result_blocking(pcm, sample_rate)[0]

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

        text, model_reported_language = await asyncio.get_running_loop().run_in_executor(
            None, self._transcribe_result_blocking, pcm, state.config.sample_rate_hz
        )
        if not text and not final:
            return

        configured = str(state.config.language or "en").lower().split("-")[0]
        language = LanguageCode(configured) if configured else LanguageCode.EN
        detection_mode = "implicit_not_exposed"
        if model_reported_language:
            try:
                language = LanguageCode(model_reported_language)
                detection_mode = "model_reported"
            except ValueError:
                logger.debug("Parakeet returned unknown language label %r", model_reported_language)

        await state.event_queue.put(
            TranscriptEvent(
                utterance_id=utterance_id,
                revision=revision,
                source_language=language,
                text=text,
                state=TranscriptState.FINAL if final else TranscriptState.PARTIAL,
                metadata={
                    "asr_model": _UPSTREAM_MODEL_ID,
                    "configured_language": configured,
                    "detected_language": model_reported_language,
                    "language_detection": detection_mode,
                    "shared_model_instance": True,
                },
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
