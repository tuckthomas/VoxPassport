"""
LiveTranslator — Real-Time Audio Capture Engine
=================================================
Manages live audio capture from physical microphones and loopback devices.

Features:
- WASAPI / sounddevice microphone capture (16kHz / 48kHz mono/stereo)
- Real-time chunking into AudioFrame packets with monotonic timestamps
- Automatic resampling to target sample rate (default 16000 Hz)
- Audio level metering (RMS / Peak dB)
- Loopback capture support (for conference/system inbound audio)
- Device discovery and selection
- Threaded non-blocking capture loop with async queue interface
- Mock audio feeder mode for automated testing / offline simulation
"""

from __future__ import annotations

import asyncio
import logging
import math
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from runtime.inference.protocol import (
    AudioBus,
    AudioFrame,
    SampleFormat,
)

logger = logging.getLogger(__name__)


@dataclass
class AudioDeviceInfo:
    """Information about an audio input/output device."""
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    is_loopback: bool = False
    is_default_input: bool = False
    is_default_output: bool = False


class AudioCaptureEngine:
    """
    Real-time audio capture engine supporting physical mics, system loopback,
    and simulated file streaming.
    """

    def __init__(
        self,
        bus: AudioBus = AudioBus.PHYSICAL_MIC,
        sample_rate_hz: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 20,  # 20ms chunks (320 samples at 16kHz)
        device_index: Optional[int] = None,
    ):
        self.bus = bus
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.chunk_duration_ms = chunk_duration_ms
        self.chunk_samples = int(sample_rate_hz * chunk_duration_ms / 1000)
        self.device_index = device_index

        self._stream = None
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._queue: asyncio.Queue[AudioFrame] = asyncio.Queue()
        self._sequence = 0
        self._stream_id = f"stream-{bus.value}-{int(time.time())}"

        # Metering
        self.current_rms_db: float = -100.0
        self.current_peak_db: float = -100.0
        self._on_level_callback: Optional[Callable[[float, float], None]] = None

    @staticmethod
    def list_devices() -> List[AudioDeviceInfo]:
        """List all available audio input and loopback devices."""
        devices: List[AudioDeviceInfo] = []
        try:
            import sounddevice as sd
            dev_list = sd.query_devices()
            default_in, default_out = sd.default.device

            for idx, d in enumerate(dev_list):
                name = d.get("name", "")
                hostapi_idx = d.get("hostapi", 0)
                try:
                    hostapi_info = sd.query_hostapis(hostapi_idx)
                    hostapi_name = hostapi_info.get("name", "")
                except Exception:
                    hostapi_name = str(hostapi_idx)

                is_loop = "loopback" in name.lower() or "stereo mix" in name.lower() or "what u hear" in name.lower()
                devices.append(
                    AudioDeviceInfo(
                        index=idx,
                        name=name,
                        hostapi=hostapi_name,
                        max_input_channels=d.get("max_input_channels", 0),
                        max_output_channels=d.get("max_output_channels", 0),
                        default_sample_rate=d.get("default_samplerate", 44100.0),
                        is_loopback=is_loop,
                        is_default_input=(idx == default_in),
                        is_default_output=(idx == default_out),
                    )
                )
        except Exception as e:
            logger.warning("Could not query sounddevice devices (%s). Providing virtual default.", e)
            devices.append(
                AudioDeviceInfo(
                    index=0,
                    name="Default System Microphone",
                    hostapi="Default",
                    max_input_channels=1,
                    max_output_channels=0,
                    default_sample_rate=16000.0,
                    is_default_input=True,
                )
            )
        return devices

    def set_level_callback(self, callback: Callable[[float, float], None]) -> None:
        """Register callback for audio level meters (rms_db, peak_db)."""
        self._on_level_callback = callback

    async def start(self) -> None:
        """Start capturing audio from the selected device."""
        if self._is_running:
            return
        self._is_running = True
        self._sequence = 0

        loop = asyncio.get_running_loop()

        try:
            import sounddevice as sd
            # Start real sounddevice capture
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate_hz,
                blocksize=self.chunk_samples,
                device=self.device_index,
                channels=self.channels,
                dtype="int16",
                callback=self._audio_callback_sd,
            )
            self._stream.start()
            logger.info("Audio capture started on %s at %d Hz", self.bus.value, self.sample_rate_hz)
        except Exception as e:
            logger.warning(
                "sounddevice capture failed or not available (%s). Starting simulated capture loop for %s.",
                e, self.bus.value
            )
            self._thread = threading.Thread(target=self._simulated_capture_loop, daemon=True)
            self._thread.start()

    def _audio_callback_sd(self, indata: bytes, frames: int, time_info, status) -> None:
        """Callback from sounddevice C thread."""
        if not self._is_running:
            return

        if status:
            logger.debug("Audio callback status: %s", status)

        # Metering
        self._compute_metering(indata)

        frame = AudioFrame(
            stream_id=self._stream_id,
            sequence=self._sequence,
            monotonic_timestamp_ns=time.monotonic_ns(),
            sample_rate_hz=self.sample_rate_hz,
            channels=self.channels,
            sample_format=SampleFormat.PCM_S16LE,
            data=bytes(indata),
        )
        self._sequence += 1
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    def _compute_metering(self, raw_bytes: bytes) -> None:
        """Calculate RMS and Peak dB from PCM 16-bit data."""
        n_samples = len(raw_bytes) // 2
        if n_samples == 0:
            return
        samples = struct.unpack(f"<{n_samples}h", raw_bytes)
        sum_sq = 0.0
        peak = 0.0
        for s in samples:
            val = abs(s) / 32768.0
            sum_sq += val * val
            if val > peak:
                peak = val

        rms = math.sqrt(sum_sq / n_samples)
        self.current_rms_db = 20.0 * math.log10(rms) if rms > 1e-5 else -100.0
        self.current_peak_db = 20.0 * math.log10(peak) if peak > 1e-5 else -100.0

        if self._on_level_callback:
            try:
                self._on_level_callback(self.current_rms_db, self.current_peak_db)
            except Exception:
                pass

    def _simulated_capture_loop(self) -> None:
        """Simulated silence / test capture loop when sound device is unavailable."""
        silence_chunk = b"\x00" * (self.chunk_samples * 2 * self.channels)
        sleep_interval = self.chunk_duration_ms / 1000.0

        while self._is_running:
            t0 = time.monotonic()
            frame = AudioFrame(
                stream_id=self._stream_id,
                sequence=self._sequence,
                monotonic_timestamp_ns=time.monotonic_ns(),
                sample_rate_hz=self.sample_rate_hz,
                channels=self.channels,
                sample_format=SampleFormat.PCM_S16LE,
                data=silence_chunk,
            )
            self._sequence += 1
            try:
                self._queue.put_nowait(frame)
            except Exception:
                pass

            elapsed = time.monotonic() - t0
            to_sleep = max(0.001, sleep_interval - elapsed)
            time.sleep(to_sleep)

    async def get_frame(self, timeout: float = 0.5) -> Optional[AudioFrame]:
        """Fetch the next audio frame from the capture queue."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def push_external_frame(self, data: bytes) -> None:
        """Inject an external audio chunk (used for mock feeds / WAV playback)."""
        self._compute_metering(data)
        frame = AudioFrame(
            stream_id=self._stream_id,
            sequence=self._sequence,
            monotonic_timestamp_ns=time.monotonic_ns(),
            sample_rate_hz=self.sample_rate_hz,
            channels=self.channels,
            sample_format=SampleFormat.PCM_S16LE,
            data=data,
        )
        self._sequence += 1
        try:
            self._queue.put_nowait(frame)
        except Exception:
            pass

    async def stop(self) -> None:
        """Stop capturing audio and release hardware devices."""
        self._is_running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning("Error closing audio stream: %s", e)
            self._stream = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
        logger.info("Audio capture stopped on %s", self.bus.value)
