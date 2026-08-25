#!/usr/bin/env python3
"""Deterministic Linux PipeWire virtual-microphone signal validation."""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import threading
import time
from pathlib import Path

SAMPLE_RATE = 48_000
CHANNELS = 2
DURATION_SECONDS = 1.5
FREQUENCY_HZ = 440.0
AMPLITUDE = 0.35
CHUNK_SECONDS = 0.020
FRAME_MAGIC = b"VPF1"
HEADER = struct.Struct("<4sQQIHBI")
SINK = "voxpassport_translation_sink"
SOURCE = "voxpassport_virtual_microphone"


def helper_path() -> Path:
    configured = os.environ.get("VOXPASSPORT_AUDIO_HELPER", "").strip()
    candidates = [Path(configured)] if configured else []
    root = Path(__file__).resolve().parents[1]
    candidates += [
        root / "crates/target/release/voxpassport-audio-helper",
        root / "crates/target/debug/voxpassport-audio-helper",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit("Linux voxpassport-audio-helper is not built")


def ensure_endpoint(devices: list[dict], endpoint_id: str, role: str) -> None:
    if not any(item.get("id") == endpoint_id and item.get("role") == role for item in devices):
        raise SystemExit(f"PipeWire endpoint {endpoint_id!r} ({role}) is not active")


def tone_payload(sequence: int, frames: int = 960) -> bytes:
    output = bytearray()
    start = sequence * frames
    for index in range(frames):
        sample = int(32767 * AMPLITUDE * math.sin(2.0 * math.pi * FREQUENCY_HZ * (start + index) / SAMPLE_RATE))
        packed = struct.pack("<h", sample)
        output.extend(packed * CHANNELS)
    return bytes(output)


def tone_frame(sequence: int) -> bytes:
    payload = tone_payload(sequence)
    return HEADER.pack(
        FRAME_MAGIC,
        sequence,
        time.monotonic_ns(),
        SAMPLE_RATE,
        CHANNELS,
        1,
        len(payload),
    ) + payload


def read_capture(proc: subprocess.Popen[bytes], output: bytearray) -> None:
    assert proc.stdout is not None
    maximum = SAMPLE_RATE * CHANNELS * 2 * 4
    while len(output) < maximum:
        header = proc.stdout.read(HEADER.size)
        if len(header) != HEADER.size:
            return
        magic, _, _, rate, channels, fmt, length = HEADER.unpack(header)
        if magic != FRAME_MAGIC or rate != SAMPLE_RATE or channels != CHANNELS or fmt != 1:
            return
        payload = proc.stdout.read(length)
        if len(payload) != length:
            return
        output.extend(payload)


def mono_samples(data: bytes) -> list[float]:
    frame_bytes = CHANNELS * 2
    usable = len(data) - (len(data) % frame_bytes)
    samples: list[float] = []
    for offset in range(0, usable, frame_bytes):
        left, right = struct.unpack_from("<hh", data, offset)
        samples.append((left + right) / 2 / 32768.0)
    return samples


def _window_metrics(samples: list[float]) -> tuple[float, float]:
    if not samples:
        return 0.0, 0.0
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    sin_sum = 0.0
    cos_sum = 0.0
    for index, value in enumerate(samples):
        angle = 2.0 * math.pi * FREQUENCY_HZ * index / SAMPLE_RATE
        sin_sum += value * math.sin(angle)
        cos_sum += value * math.cos(angle)
    tone_amplitude = 2.0 * math.sqrt(sin_sum * sin_sum + cos_sum * cos_sum) / len(samples)
    return rms, tone_amplitude


def tone_metrics(samples: list[float]) -> tuple[float, float]:
    if not samples:
        return 0.0, 0.0
    window = min(len(samples), SAMPLE_RATE // 2)
    if len(samples) <= window:
        return _window_metrics(samples)
    step = max(1, SAMPLE_RATE // 10)
    best = (0.0, 0.0)
    for start in range(0, len(samples) - window + 1, step):
        current = _window_metrics(samples[start : start + window])
        if current[1] > best[1]:
            best = current
    return best


def process_error(label: str, proc: subprocess.Popen[bytes]) -> str:
    stderr = b""
    if proc.stderr is not None:
        try:
            stderr = proc.stderr.read()
        except Exception:
            pass
    return f"{label} exited with code {proc.returncode}: {stderr.decode(errors='replace').strip()}"


def main() -> None:
    helper = helper_path()
    devices = json.loads(subprocess.check_output([str(helper), "devices"], text=True))["devices"]
    ensure_endpoint(devices, SINK, "render_output")
    ensure_endpoint(devices, SOURCE, "physical_microphone")

    capture = subprocess.Popen(
        [
            str(helper), "capture-mic",
            "--endpoint", SOURCE,
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--chunk-ms", "20",
            "--queue", "8",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    captured = bytearray()
    reader = threading.Thread(target=read_capture, args=(capture, captured), daemon=True)
    reader.start()
    try:
        time.sleep(0.35)
        if capture.poll() is not None:
            raise SystemExit(process_error("capture helper", capture))

        render = subprocess.Popen(
            [
                str(helper), "render",
                "--endpoint", SINK,
                "--rate", str(SAMPLE_RATE),
                "--channels", str(CHANNELS),
                "--queue", "16",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert render.stdin is not None
        chunks = int(DURATION_SECONDS / CHUNK_SECONDS)
        next_deadline = time.monotonic()
        for sequence in range(chunks):
            render.stdin.write(tone_frame(sequence))
            render.stdin.flush()
            # Exercise the bounded render transport as a live session uses it:
            # provider/native PCM arrives in 20 ms chunks rather than as a
            # 1.5-second stdin burst that intentionally overflows the queue.
            next_deadline += CHUNK_SECONDS
            remaining = next_deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)

        # Keep stdin open briefly after the final realtime chunk so the helper
        # worker and PipeWire-Pulse playback buffer can drain before EOF causes
        # the helper to stop its render stream.
        time.sleep(0.30)
        render.stdin.close()
        if render.wait(timeout=8.0) != 0:
            raise SystemExit(process_error("render helper", render))
        time.sleep(0.35)
        if capture.poll() is not None:
            raise SystemExit(process_error("capture helper", capture))
    finally:
        if capture.poll() is None:
            capture.terminate()
        try:
            capture.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            capture.kill()
            capture.wait()
        reader.join(timeout=1.0)

    samples = mono_samples(bytes(captured))
    rms, tone_amplitude = tone_metrics(samples)
    print(f"captured_bytes={len(captured)} strongest_window_rms={rms:.5f} tone_440hz={tone_amplitude:.5f}")
    if len(captured) < SAMPLE_RATE * CHANNELS * 2 // 4:
        raise SystemExit("FAIL: too little PCM was captured from VoxPassport Virtual Microphone")
    if rms < 0.01:
        raise SystemExit("FAIL: captured virtual-microphone PCM is effectively silent")
    if tone_amplitude < 0.08:
        raise SystemExit("FAIL: deterministic 440 Hz component did not cross the virtual cable")
    print("PASS: VoxPassport Translation Sink -> VoxPassport Virtual Microphone PCM bridge validated")


if __name__ == "__main__":
    main()
