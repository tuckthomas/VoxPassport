"""Native audio render output over the local helper's framed-PCM stdin."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from runtime.inference.native_audio_bridge import (
    FRAME_HEADER,
    FRAME_MAGIC,
    MAX_FRAME_BYTES,
    NativeAudioBridge,
    NativeAudioBridgeError,
)
from runtime.inference.protocol import AudioFrame, SampleFormat
from runtime.inference.translation_session import TranslatedAudioChunk


@dataclass(frozen=True, slots=True)
class NativeAudioRenderConfig:
    endpoint_id: str | None = None
    sample_rate_hz: int = 24000
    channels: int = 1
    queue_capacity: int = 16

    def validate(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if not 1 <= self.queue_capacity <= 512:
            raise ValueError("queue_capacity must be between 1 and 512")


class NativeAudioRender:
    def __init__(
        self,
        *,
        process: asyncio.subprocess.Process,
        config: NativeAudioRenderConfig,
    ) -> None:
        self.process = process
        self.config = config
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._sequence = 0

    @classmethod
    async def open(
        cls,
        bridge: NativeAudioBridge,
        config: NativeAudioRenderConfig | None = None,
    ) -> "NativeAudioRender":
        selected = config or NativeAudioRenderConfig()
        selected.validate()
        probe = await bridge.probe(force=True)
        if probe is None:
            raise NativeAudioBridgeError("native audio helper is unavailable")
        if not probe.capabilities.get("render_output"):
            raise NativeAudioBridgeError("native audio helper does not report render output support")
        args = [
            str(probe.helper_path),
            "render",
            "--rate", str(selected.sample_rate_hz),
            "--channels", str(selected.channels),
            "--queue", str(selected.queue_capacity),
        ]
        if selected.endpoint_id:
            args.extend(["--endpoint", selected.endpoint_id])
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None:
            process.kill()
            await process.wait()
            raise NativeAudioBridgeError("native render helper stdin pipe unavailable")
        # The helper validates/opens WASAPI before it consumes the first frame.
        # Give immediate startup failures a short window to surface.
        await asyncio.sleep(0.05)
        if process.returncode is not None:
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            raise NativeAudioBridgeError(
                f"native render helper exited during startup: "
                f"{stderr.decode('utf-8', errors='replace').strip() or process.returncode}"
            )
        return cls(process=process, config=selected)

    async def write_frame(self, frame: AudioFrame) -> None:
        if self._closed or self.process.stdin is None:
            raise NativeAudioBridgeError("native render output is closed")
        if frame.sample_rate_hz != self.config.sample_rate_hz or frame.channels != self.config.channels:
            raise NativeAudioBridgeError(
                f"native render expects {self.config.sample_rate_hz} Hz / {self.config.channels} channel(s)"
            )
        payload = encode_frame(frame)
        async with self._write_lock:
            if self.process.returncode is not None:
                raise NativeAudioBridgeError("native render helper has exited")
            self.process.stdin.write(payload)
            await self.process.stdin.drain()

    async def write_translated_audio(self, chunk: TranslatedAudioChunk) -> None:
        frame = AudioFrame(
            stream_id="translated-native-output",
            sequence=self._sequence,
            monotonic_timestamp_ns=time.monotonic_ns(),
            sample_rate_hz=chunk.sample_rate_hz,
            channels=chunk.channels,
            sample_format=chunk.sample_format,
            data=chunk.data,
        )
        self._sequence += 1
        await self.write_frame(frame)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
                await self.process.stdin.wait_closed()
            except Exception:
                pass
        if self.process.returncode is None:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()

    async def __aenter__(self) -> "NativeAudioRender":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


def encode_frame(frame: AudioFrame) -> bytes:
    if len(frame.data) > MAX_FRAME_BYTES:
        raise NativeAudioBridgeError(
            f"native audio frame payload {len(frame.data)} exceeds {MAX_FRAME_BYTES} byte limit"
        )
    format_id = {
        SampleFormat.PCM_S16LE: 1,
        SampleFormat.PCM_F32LE: 2,
    }.get(frame.sample_format)
    if format_id is None:
        raise NativeAudioBridgeError(f"unsupported native sample format {frame.sample_format}")
    return FRAME_HEADER.pack(
        FRAME_MAGIC,
        frame.sequence,
        frame.monotonic_timestamp_ns,
        frame.sample_rate_hz,
        frame.channels,
        format_id,
        len(frame.data),
    ) + frame.data
