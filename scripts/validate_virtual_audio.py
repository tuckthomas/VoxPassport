#!/usr/bin/env python3
"""Validate the installed VoxPassport Windows virtual-audio cable.

The test proves more than endpoint enumeration: it renders deterministic PCM to
"VoxPassport Translation Sink", captures "VoxPassport Virtual Microphone", and
fails unless non-silent PCM crosses the driver bridge.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import struct
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.inference.native_audio_bridge import NativeAudioBridge, NativeAudioCaptureConfig
from runtime.inference.native_audio_output import NativeAudioRender, NativeAudioRenderConfig
from runtime.inference.protocol import AudioFrame, SampleFormat


RENDER_NAME = "VoxPassport Translation Sink"
CAPTURE_NAME = "VoxPassport Virtual Microphone"
SAMPLE_RATE = 48_000
CHANNELS = 2
CHUNK_MS = 20
TONE_HZ = 440.0
AMPLITUDE = 12_000


def _find_endpoint(devices: list[dict], *, role: str, expected_name: str) -> dict:
    exact = [
        item for item in devices
        if str(item.get("role")) == role
        and str(item.get("name", "")).strip().casefold() == expected_name.casefold()
    ]
    if exact:
        return exact[0]
    fuzzy = [
        item for item in devices
        if str(item.get("role")) == role
        and expected_name.casefold() in str(item.get("name", "")).casefold()
    ]
    if fuzzy:
        return fuzzy[0]
    visible = [f"{item.get('role')}: {item.get('name')}" for item in devices]
    raise RuntimeError(
        f"Could not find {role} endpoint {expected_name!r}. Available endpoints:\n  "
        + "\n  ".join(visible)
    )


def _tone_chunk(sequence: int, start_sample: int) -> AudioFrame:
    frames = SAMPLE_RATE * CHUNK_MS // 1000
    values: list[int] = []
    for index in range(frames):
        sample_index = start_sample + index
        value = int(AMPLITUDE * math.sin(2.0 * math.pi * TONE_HZ * sample_index / SAMPLE_RATE))
        values.extend((value, value))
    data = struct.pack(f"<{len(values)}h", *values)
    return AudioFrame(
        stream_id="virtual-audio-validation",
        sequence=sequence,
        monotonic_timestamp_ns=time.monotonic_ns(),
        sample_rate_hz=SAMPLE_RATE,
        channels=CHANNELS,
        sample_format=SampleFormat.PCM_S16LE,
        data=data,
    )


async def _collect_capture(capture, seconds: float) -> bytes:
    deadline = time.monotonic() + seconds
    chunks: list[bytes] = []
    iterator = capture.frames().__aiter__()
    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        try:
            frame = await asyncio.wait_for(iterator.__anext__(), timeout=min(0.5, remaining))
        except asyncio.TimeoutError:
            continue
        except StopAsyncIteration:
            break
        if frame.sample_format != SampleFormat.PCM_S16LE:
            raise RuntimeError(f"Capture returned unexpected format {frame.sample_format}")
        chunks.append(frame.data)
    return b"".join(chunks)


def _pcm_stats(data: bytes) -> tuple[float, int, int]:
    usable = len(data) - (len(data) % 2)
    if usable <= 0:
        return 0.0, 0, 0
    samples = struct.unpack(f"<{usable // 2}h", data[:usable])
    peak = max((abs(value) for value in samples), default=0)
    mean_square = sum(float(value) * float(value) for value in samples) / max(1, len(samples))
    rms = math.sqrt(mean_square)
    nonzero = sum(1 for value in samples if value != 0)
    return rms, peak, nonzero


async def validate(min_rms: float) -> int:
    bridge = NativeAudioBridge(project_root=PROJECT_ROOT)
    probe = await bridge.probe(force=True)
    if probe is None:
        print("FAIL: native audio helper is not built or cannot be probed", file=sys.stderr)
        return 2

    payload = await bridge.devices_payload()
    devices = payload.get("devices") or []
    render_endpoint = _find_endpoint(devices, role="render_output", expected_name=RENDER_NAME)
    capture_endpoint = _find_endpoint(devices, role="physical_microphone", expected_name=CAPTURE_NAME)

    print(f"Render endpoint : {render_endpoint['name']} [{render_endpoint['id']}]")
    print(f"Capture endpoint: {capture_endpoint['name']} [{capture_endpoint['id']}]")

    capture = await bridge.open_microphone_capture(NativeAudioCaptureConfig(
        endpoint_id=str(capture_endpoint["id"]),
        sample_rate_hz=SAMPLE_RATE,
        channels=CHANNELS,
        chunk_duration_ms=CHUNK_MS,
        queue_capacity=32,
    ))
    render = await NativeAudioRender.open(bridge, NativeAudioRenderConfig(
        endpoint_id=str(render_endpoint["id"]),
        sample_rate_hz=SAMPLE_RATE,
        channels=CHANNELS,
        queue_capacity=32,
    ))

    try:
        collector = asyncio.create_task(_collect_capture(capture, 1.8))
        await asyncio.sleep(0.15)
        sequence = 0
        start_sample = 0
        chunks = 50  # 1 second at 20 ms/chunk.
        for _ in range(chunks):
            frame = _tone_chunk(sequence, start_sample)
            await render.write_frame(frame)
            sequence += 1
            start_sample += SAMPLE_RATE * CHUNK_MS // 1000
            await asyncio.sleep(CHUNK_MS / 1000.0)
        await asyncio.sleep(0.25)
        captured = await collector
    finally:
        await render.close()
        await capture.close()

    rms, peak, nonzero = _pcm_stats(captured)
    print(f"Captured bytes  : {len(captured)}")
    print(f"Captured RMS    : {rms:.1f}")
    print(f"Captured peak   : {peak}")
    print(f"Nonzero samples : {nonzero}")

    if len(captured) < SAMPLE_RATE * CHANNELS * 2 // 4:
        print("FAIL: too little PCM was captured from the virtual microphone", file=sys.stderr)
        return 3
    if rms < min_rms or peak < int(min_rms * 2) or nonzero == 0:
        print(
            "FAIL: endpoints exist, but translated-sink PCM did not cross the virtual cable",
            file=sys.stderr,
        )
        return 4

    print("PASS: PCM rendered to VoxPassport Translation Sink was captured from VoxPassport Virtual Microphone")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the installed VoxPassport virtual audio cable")
    parser.add_argument("--min-rms", type=float, default=500.0, help="minimum captured int16 RMS required for PASS")
    args = parser.parse_args()
    try:
        return asyncio.run(validate(args.min_rms))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
