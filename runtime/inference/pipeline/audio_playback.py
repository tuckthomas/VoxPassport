"""Real-time TTS audio playback with stateful sample-rate conversion."""

from __future__ import annotations

import asyncio
import logging
from math import gcd
from typing import Optional

import numpy as np
from scipy.signal import resample_poly

from runtime.inference.protocol import AudioBus, SampleFormat, TtsAudioChunk

logger = logging.getLogger(__name__)


class AudioPlaybackEngine:
    def __init__(
        self,
        bus: AudioBus = AudioBus.VIRTUAL_MIC,
        sample_rate_hz: int = 24000,
        channels: int = 1,
        device_index: Optional[int] = None,
    ) -> None:
        self.bus = bus
        self.sample_rate_hz = int(sample_rate_hz)
        self.channels = int(channels)
        self.device_index = device_index
        self._stream = None
        self._is_running = False
        self._queue: asyncio.Queue[TtsAudioChunk] = asyncio.Queue(maxsize=100)
        self._consumer_task: Optional[asyncio.Task] = None
        self._resample_source_rate: Optional[int] = None
        self._resample_tail = np.empty(0, dtype=np.float32)
        self._tail_samples = 96
        self.chunks_played = 0
        self.bytes_played = 0

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self.chunks_played = 0
        self.bytes_played = 0
        self._reset_resampler()
        self._drain_queue()
        try:
            import sounddevice as sd
            self._stream = sd.RawOutputStream(
                samplerate=self.sample_rate_hz,
                device=self.device_index,
                channels=self.channels,
                dtype="int16",
            )
            self._stream.start()
            logger.info(
                "Playback opened on %s (device=%s, rate=%d)",
                self.bus.value,
                self.device_index,
                self.sample_rate_hz,
            )
        except Exception as exc:
            logger.warning("Audio output unavailable for %s: %s; using drain mode", self.bus.value, exc)
            self._stream = None
        self._consumer_task = asyncio.create_task(
            self._consumer_loop(), name=f"audio-playback-{self.bus.value}"
        )

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _reset_resampler(self) -> None:
        self._resample_source_rate = None
        self._resample_tail = np.empty(0, dtype=np.float32)

    async def enqueue_chunk(self, chunk: TtsAudioChunk) -> None:
        if not self._is_running:
            return
        await self._queue.put(chunk)

    async def _consumer_loop(self) -> None:
        try:
            while self._is_running:
                try:
                    chunk = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if not chunk.data:
                    continue
                pcm_s16 = self._convert_and_resample(chunk)
                if not pcm_s16:
                    continue
                self.chunks_played += 1
                self.bytes_played += len(pcm_s16)
                if self._stream:
                    try:
                        self._stream.write(pcm_s16)
                    except Exception as exc:
                        logger.warning("Playback write failed on %s: %s", self.bus.value, exc)
                else:
                    n_samples = len(pcm_s16) // max(1, 2 * self.channels)
                    await asyncio.sleep(n_samples / max(1, self.sample_rate_hz))
        except asyncio.CancelledError:
            pass

    def _convert_to_s16le(self, data: bytes, fmt: SampleFormat) -> bytes:
        return self._convert_and_resample(
            TtsAudioChunk(
                utterance_id="",
                segment_id="",
                sequence=0,
                sample_rate_hz=self.sample_rate_hz,
                sample_format=fmt,
                data=data,
            )
        )

    def _decode_samples(self, chunk: TtsAudioChunk) -> np.ndarray:
        if chunk.sample_format == SampleFormat.PCM_S16LE:
            return np.frombuffer(chunk.data, dtype="<i2").astype(np.float32)
        if chunk.sample_format == SampleFormat.PCM_F32LE:
            samples = np.frombuffer(chunk.data, dtype="<f4").astype(np.float32)
            return np.clip(samples, -1.0, 1.0) * 32767.0
        raise ValueError(f"Unsupported playback sample format: {chunk.sample_format}")

    def _resample(self, samples: np.ndarray, source_rate: int) -> np.ndarray:
        if source_rate == self.sample_rate_hz:
            self._reset_resampler()
            return samples

        if self._resample_source_rate != source_rate:
            self._resample_source_rate = source_rate
            self._resample_tail = np.empty(0, dtype=np.float32)

        previous_tail = self._resample_tail
        combined = np.concatenate((previous_tail, samples)) if previous_tail.size else samples
        factor = gcd(source_rate, self.sample_rate_hz)
        up = self.sample_rate_hz // factor
        down = source_rate // factor
        converted = resample_poly(combined, up, down).astype(np.float32, copy=False)

        if previous_tail.size:
            prefix = int(round(previous_tail.size * up / down))
            converted = converted[min(prefix, converted.size):]

        keep = min(self._tail_samples, combined.size)
        self._resample_tail = combined[-keep:].copy() if keep else np.empty(0, dtype=np.float32)
        return converted

    def _convert_and_resample(self, chunk: TtsAudioChunk) -> bytes:
        samples = self._decode_samples(chunk)
        if samples.size == 0:
            return b""
        source_rate = int(chunk.sample_rate_hz or self.sample_rate_hz)
        samples = self._resample(samples, source_rate)
        if samples.size == 0:
            return b""
        return np.clip(np.rint(samples), -32768, 32767).astype("<i2").tobytes()

    async def stop(self) -> None:
        self._is_running = False
        task = self._consumer_task
        self._consumer_task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning("Error closing playback stream: %s", exc)
            self._stream = None
        self._drain_queue()
        self._reset_resampler()
        logger.info("Playback stopped on %s (%d chunks)", self.bus.value, self.chunks_played)
