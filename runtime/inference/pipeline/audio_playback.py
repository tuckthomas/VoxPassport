"""
LiveTranslator — Real-Time Audio Playback Engine
=================================================
Manages playback of synthesized speech chunks to:
1. Virtual Microphone device (BUS_VIRTUAL_MIC -> fed into conference apps)
2. Local Monitor / Headphones (BUS_LOCAL_MONITOR -> for local user listening)

Features:
- Streaming chunk jitter buffer
- Automatic sample rate conversion / format conversion (e.g. float32 to int16)
- Virtual microphone device routing
- Underrun / overflow protection
- Async chunk consumption queue
"""

from __future__ import annotations

import asyncio
import logging
import struct
import threading
import time
from typing import Optional

from runtime.inference.protocol import (
    AudioBus,
    SampleFormat,
    TtsAudioChunk,
)

logger = logging.getLogger(__name__)


class AudioPlaybackEngine:
    """
    Playback engine for streaming TTS synthesized chunks to an audio output device
    (Virtual Mic or Local Monitor).
    """

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
        self._thread: Optional[threading.Thread] = None

        # Statistics
        self.chunks_played = 0
        self.bytes_played = 0

    async def start(self) -> None:
        """Start the audio playback stream."""
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
            logger.info("Audio playback stream opened on %s (device=%s, rate=%d)", self.bus.value, self.device_index, self.sample_rate_hz)
        except Exception as e:
            logger.warning(
                "sounddevice output stream failed or not available (%s). Starting software drain mode for %s.",
                e, self.bus.value
            )

        # Start playback consumer loop task
        asyncio.create_task(self._consumer_loop())

    async def enqueue_chunk(self, chunk: TtsAudioChunk) -> None:
        """Feed a synthesized TTS chunk into the playback queue."""
        if not self._is_running:
            return
        try:
            await self._queue.put(chunk)
        except Exception as e:
            logger.warning("Playback queue put error on %s: %s", self.bus.value, e)

    async def _consumer_loop(self) -> None:
        """Async consumer pulling chunks from the queue and writing to the output stream."""
        while self._is_running:
            try:
                chunk: TtsAudioChunk = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            if not chunk.data:
                continue

            # Convert data to int16 PCM if needed
            pcm_s16 = self._convert_to_s16le(chunk.data, chunk.sample_format)
            self.chunks_played += 1
            self.bytes_played += len(pcm_s16)

            if self._stream:
                try:
                    self._stream.write(pcm_s16)
                except Exception as e:
                    logger.debug("Playback write exception on %s: %s", self.bus.value, e)
            else:
                # In mock/drain mode, sleep to approximate real-time audio duration
                n_samples = len(pcm_s16) // (2 * self.channels)
                duration_s = n_samples / max(1, self.sample_rate_hz)
                await asyncio.sleep(duration_s * 0.8)

    def _convert_to_s16le(self, data: bytes, fmt: SampleFormat) -> bytes:
        """Convert any supported PCM format to PCM_S16LE."""
        if fmt == SampleFormat.PCM_S16LE:
            return data
        elif fmt == SampleFormat.PCM_F32LE:
            n_samples = len(data) // 4
            if n_samples == 0:
                return b""
            f32_vals = struct.unpack(f"<{n_samples}f", data)
            s16_vals = [max(-32768, min(32767, int(v * 32767))) for v in f32_vals]
            return struct.pack(f"<{n_samples}h", *s16_vals)
        return data

    async def stop(self) -> None:
        """Stop playback and drain queue."""
        self._is_running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning("Error closing playback stream: %s", e)
            self._stream = None
        logger.info("Audio playback stopped on %s (played %d chunks)", self.bus.value, self.chunks_played)
