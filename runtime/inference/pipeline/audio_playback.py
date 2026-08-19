"""VoxPassport — real-time TTS audio playback engine.

Consumes model-native PCM chunks and converts/resamples them to the fixed output
device rate. This is required when hot-swapping 24 kHz engines (Higgs/OmniVoice)
and 48 kHz engines (MOSS) during one conference session.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np

from runtime.inference.protocol import AudioBus, SampleFormat, TtsAudioChunk

logger = logging.getLogger(__name__)


class AudioPlaybackEngine:
    def __init__(
        self,
        bus: AudioBus = AudioBus.VIRTUAL_MIC,
        sample_rate_hz: int = 24000,
        channels: int = 1,
        device_index: Optional[int] = None,
    ):
        self.bus = bus
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.device_index = device_index
        self._stream = None
        self._is_running = False
        self._queue: asyncio.Queue[TtsAudioChunk] = asyncio.Queue(maxsize=100)
        self.chunks_played = 0
        self.bytes_played = 0

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self.chunks_played = 0
        self.bytes_played = 0
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
                "Audio playback stream opened on %s (device=%s, rate=%d)",
                self.bus.value, self.device_index, self.sample_rate_hz,
            )
        except Exception as exc:
            logger.warning(
                "sounddevice output stream failed or not available (%s). "
                "Starting software drain mode for %s.", exc, self.bus.value,
            )
        asyncio.create_task(self._consumer_loop())

    async def enqueue_chunk(self, chunk: TtsAudioChunk) -> None:
        if not self._is_running:
            return
        await self._queue.put(chunk)

    async def _consumer_loop(self) -> None:
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
                    logger.debug("Playback write exception on %s: %s", self.bus.value, exc)
            else:
                n_samples = len(pcm_s16) // (2 * self.channels)
                duration_s = n_samples / max(1, self.sample_rate_hz)
                await asyncio.sleep(duration_s * 0.8)

    def _convert_and_resample(self, chunk: TtsAudioChunk) -> bytes:
        """Convert the declared chunk format and sample rate to output S16LE PCM."""
        if chunk.sample_format == SampleFormat.PCM_S16LE:
            samples = np.frombuffer(chunk.data, dtype="<i2").astype(np.float32)
        elif chunk.sample_format == SampleFormat.PCM_F32LE:
            samples = np.frombuffer(chunk.data, dtype="<f4").astype(np.float32)
            samples = np.clip(samples, -1.0, 1.0) * 32767.0
        else:
            raise ValueError(f"Unsupported playback sample format: {chunk.sample_format}")
        if samples.size == 0:
            return b""
        source_rate = int(chunk.sample_rate_hz or self.sample_rate_hz)
        if source_rate != self.sample_rate_hz:
            out_count = max(1, int(round(samples.size * self.sample_rate_hz / source_rate)))
            if samples.size == 1:
                samples = np.repeat(samples, out_count)
            else:
                src_positions = np.arange(samples.size, dtype=np.float64)
                dst_positions = np.linspace(
                    0.0, float(samples.size - 1), out_count, dtype=np.float64
                )
                samples = np.interp(dst_positions, src_positions, samples).astype(np.float32)
        return np.clip(np.rint(samples), -32768, 32767).astype("<i2").tobytes()

    async def stop(self) -> None:
        self._is_running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning("Error closing playback stream: %s", exc)
            self._stream = None
        logger.info(
            "Audio playback stopped on %s (played %d chunks)",
            self.bus.value, self.chunks_played,
        )
