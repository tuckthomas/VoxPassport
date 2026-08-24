"""Native desktop audio helper bridge.

Raw PCM travels over a local subprocess pipe, never through React state or REST.
The Expo client consumes only status/device/control metadata from the daemon.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Any

from runtime.inference.protocol import AudioFrame, SampleFormat


NATIVE_AUDIO_PROTOCOL = "voxpassport.native-audio.v1"
FRAME_MAGIC = b"VPF1"
FRAME_HEADER = struct.Struct("<4sQQIHBI")
MAX_FRAME_BYTES = 4 * 1024 * 1024


class NativeAudioBridgeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NativeAudioProbe:
    helper_path: Path
    endpoint_count: int
    capabilities: dict[str, bool]


@dataclass(frozen=True, slots=True)
class NativeAudioCaptureConfig:
    endpoint_id: str | None = None
    sample_rate_hz: int = 16000
    channels: int = 1
    chunk_duration_ms: int = 20
    queue_capacity: int = 8

    def validate(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if not 1 <= self.chunk_duration_ms <= 1000:
            raise ValueError("chunk_duration_ms must be between 1 and 1000")
        if not 1 <= self.queue_capacity <= 512:
            raise ValueError("queue_capacity must be between 1 and 512")


class NativeAudioBridge:
    def __init__(self, *, project_root: Path, helper_path: Path | None = None) -> None:
        self.project_root = Path(project_root)
        self._explicit_helper = Path(helper_path) if helper_path else None
        self._probe_cache: tuple[float, NativeAudioProbe | None] | None = None

    def resolve_helper_path(self) -> Path | None:
        candidates: list[Path] = []
        if self._explicit_helper:
            candidates.append(self._explicit_helper)
        configured = os.getenv("VOXPASSPORT_AUDIO_HELPER", "").strip()
        if configured:
            candidates.append(Path(configured).expanduser())
        executable = "voxpassport-audio-helper.exe" if sys.platform == "win32" else "voxpassport-audio-helper"
        candidates.extend([
            self.project_root / "target" / "release" / executable,
            self.project_root / "target" / "debug" / executable,
            self.project_root / "crates" / "audio-windows" / "target" / "release" / executable,
            self.project_root / "crates" / "audio-windows" / "target" / "debug" / executable,
        ])
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                continue
            if resolved.is_file():
                return resolved
        return None

    async def probe(self, *, force: bool = False) -> NativeAudioProbe | None:
        now = time.monotonic()
        if not force and self._probe_cache and now - self._probe_cache[0] < 3.0:
            return self._probe_cache[1]
        helper = self.resolve_helper_path()
        if helper is None:
            self._probe_cache = (now, None)
            return None
        try:
            payload = await self._run_json_command(helper, "probe", timeout=5.0)
            if payload.get("protocol") != NATIVE_AUDIO_PROTOCOL:
                raise NativeAudioBridgeError(
                    f"unsupported native audio protocol {payload.get('protocol')!r}"
                )
            capabilities = payload.get("capabilities")
            if not isinstance(capabilities, dict):
                raise NativeAudioBridgeError("native audio probe did not return capabilities")
            result = NativeAudioProbe(
                helper_path=helper,
                endpoint_count=int(payload.get("endpoint_count", 0)),
                capabilities={str(k): bool(v) for k, v in capabilities.items()},
            )
        except Exception:
            result = None
        self._probe_cache = (now, result)
        return result

    async def status_payload(self) -> dict[str, Any]:
        probe = await self.probe()
        if probe is None:
            return {
                "schema_version": 1,
                "transport": "runtime_native_service",
                "platform": sys.platform,
                "service_connected": False,
                "capabilities": {
                    "device_enumeration": False,
                    "physical_microphone_capture": False,
                    "loopback_capture": False,
                    "virtual_microphone_output": False,
                },
                "note": "native Windows audio helper is not built or could not be probed",
            }
        return {
            "schema_version": 1,
            "transport": "runtime_native_service",
            "platform": "windows",
            "service_connected": True,
            "capabilities": {
                "device_enumeration": bool(probe.capabilities.get("device_enumeration")),
                "physical_microphone_capture": bool(probe.capabilities.get("physical_microphone_capture")),
                "loopback_capture": bool(probe.capabilities.get("loopback_capture")),
                "virtual_microphone_output": bool(probe.capabilities.get("virtual_microphone_output")),
            },
            "note": f"native helper connected; {probe.endpoint_count} endpoint roles discovered",
        }

    async def devices_payload(self) -> dict[str, Any]:
        probe = await self.probe()
        if probe is None:
            return {"schema_version": 1, "devices": []}
        payload = await self._run_json_command(probe.helper_path, "devices", timeout=5.0)
        devices = payload.get("devices")
        if not isinstance(devices, list):
            raise NativeAudioBridgeError("native audio helper returned invalid device list")
        return {"schema_version": 1, "devices": devices}

    async def open_microphone_capture(
        self,
        config: NativeAudioCaptureConfig | None = None,
    ) -> "NativeAudioCapture":
        return await self._open_capture("capture-mic", "native-microphone", config or NativeAudioCaptureConfig())

    async def open_loopback_capture(
        self,
        config: NativeAudioCaptureConfig | None = None,
    ) -> "NativeAudioCapture":
        return await self._open_capture("capture-loopback", "native-loopback", config or NativeAudioCaptureConfig())

    async def _open_capture(
        self,
        command: str,
        stream_id: str,
        config: NativeAudioCaptureConfig,
    ) -> "NativeAudioCapture":
        config.validate()
        probe = await self.probe(force=True)
        if probe is None:
            raise NativeAudioBridgeError("native audio helper is unavailable")
        args = [
            str(probe.helper_path),
            command,
            "--rate", str(config.sample_rate_hz),
            "--channels", str(config.channels),
            "--chunk-ms", str(config.chunk_duration_ms),
            "--queue", str(config.queue_capacity),
        ]
        if config.endpoint_id:
            args.extend(["--endpoint", config.endpoint_id])
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdout is None:
            process.kill()
            await process.wait()
            raise NativeAudioBridgeError("native audio helper stdout pipe unavailable")
        return NativeAudioCapture(process=process, stream_id=stream_id)

    @staticmethod
    async def _run_json_command(helper: Path, command: str, *, timeout: float) -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            str(helper),
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise NativeAudioBridgeError(f"native audio {command} command timed out")
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise NativeAudioBridgeError(f"native audio {command} failed: {detail or process.returncode}")
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except Exception as exc:
            raise NativeAudioBridgeError(f"native audio {command} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise NativeAudioBridgeError(f"native audio {command} response must be an object")
        return payload


class NativeAudioCapture:
    def __init__(self, *, process: asyncio.subprocess.Process, stream_id: str) -> None:
        self.process = process
        self.stream_id = stream_id
        self._closed = False

    async def frames(self) -> AsyncIterator[AudioFrame]:
        if self.process.stdout is None:
            raise NativeAudioBridgeError("capture stdout pipe unavailable")
        reader = self.process.stdout
        while not self._closed:
            try:
                header = await reader.readexactly(FRAME_HEADER.size)
            except asyncio.IncompleteReadError as exc:
                if self.process.returncode in {0, None} and not self._closed and exc.partial:
                    raise NativeAudioBridgeError("native audio frame header was truncated") from exc
                break
            sequence, timestamp_ns, sample_rate, channels, sample_format, payload_length = parse_frame_header(header)
            if payload_length > MAX_FRAME_BYTES:
                raise NativeAudioBridgeError(
                    f"native audio frame payload {payload_length} exceeds {MAX_FRAME_BYTES} byte limit"
                )
            try:
                data = await reader.readexactly(payload_length)
            except asyncio.IncompleteReadError as exc:
                raise NativeAudioBridgeError("native audio frame payload was truncated") from exc
            yield AudioFrame(
                stream_id=self.stream_id,
                sequence=sequence,
                monotonic_timestamp_ns=timestamp_ns,
                sample_rate_hz=sample_rate,
                channels=channels,
                sample_format=sample_format,
                data=data,
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def __aenter__(self) -> "NativeAudioCapture":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


def parse_frame_header(header: bytes) -> tuple[int, int, int, int, SampleFormat, int]:
    if len(header) != FRAME_HEADER.size:
        raise NativeAudioBridgeError("native audio frame header has invalid length")
    magic, sequence, timestamp_ns, sample_rate, channels, format_id, payload_length = FRAME_HEADER.unpack(header)
    if magic != FRAME_MAGIC:
        raise NativeAudioBridgeError("native audio frame magic mismatch")
    try:
        sample_format = {
            1: SampleFormat.PCM_S16LE,
            2: SampleFormat.PCM_F32LE,
        }[format_id]
    except KeyError as exc:
        raise NativeAudioBridgeError(f"unsupported native sample format id {format_id}") from exc
    if sample_rate <= 0 or channels <= 0:
        raise NativeAudioBridgeError("native audio frame reports invalid sample shape")
    return sequence, timestamp_ns, sample_rate, channels, sample_format, payload_length
