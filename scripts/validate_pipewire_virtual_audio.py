#!/usr/bin/env python3
"""Deterministic Linux PipeWire virtual-microphone signal validation."""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path

SAMPLE_RATE = 48_000
CHANNELS = 2
DURATION_SECONDS = 1.5
FREQUENCY_HZ = 440.0
AMPLITUDE = 0.35
SINK = "voxpassport_translation_sink"
SOURCE = "voxpassport_virtual_microphone"


def require(command: str) -> None:
    if shutil.which(command) is None:
        raise SystemExit(f"Required command {command!r} was not found on PATH")


def make_tone() -> bytes:
    frames = int(SAMPLE_RATE * DURATION_SECONDS)
    output = bytearray()
    for index in range(frames):
        sample = int(32767 * AMPLITUDE * math.sin(2.0 * math.pi * FREQUENCY_HZ * index / SAMPLE_RATE))
        packed = struct.pack("<h", sample)
        output.extend(packed * CHANNELS)
    return bytes(output)


def mono_samples(data: bytes) -> list[float]:
    frame_bytes = CHANNELS * 2
    usable = len(data) - (len(data) % frame_bytes)
    samples: list[float] = []
    for offset in range(0, usable, frame_bytes):
        total = 0
        for channel in range(CHANNELS):
            total += struct.unpack_from("<h", data, offset + channel * 2)[0]
        samples.append(total / CHANNELS / 32768.0)
    return samples


def tone_metrics(samples: list[float]) -> tuple[float, float]:
    if not samples:
        return 0.0, 0.0
    # Ignore startup/shutdown transients and retain at most one second.
    trim = min(len(samples) // 10, SAMPLE_RATE // 4)
    if len(samples) > trim * 2:
        samples = samples[trim:-trim]
    samples = samples[:SAMPLE_RATE]
    rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples)))
    sin_sum = 0.0
    cos_sum = 0.0
    for index, value in enumerate(samples):
        angle = 2.0 * math.pi * FREQUENCY_HZ * index / SAMPLE_RATE
        sin_sum += value * math.sin(angle)
        cos_sum += value * math.cos(angle)
    tone_amplitude = 2.0 * math.sqrt(sin_sum * sin_sum + cos_sum * cos_sum) / max(1, len(samples))
    return rms, tone_amplitude


def ensure_endpoint(kind: str, endpoint: str) -> None:
    command = ["pactl", "list", "short", kind]
    output = subprocess.check_output(command, text=True)
    names = {line.split()[1] for line in output.splitlines() if len(line.split()) >= 2}
    if endpoint not in names:
        raise SystemExit(f"PipeWire endpoint {endpoint!r} is not active; run drivers/linux/virtual-audio/install.sh")


def main() -> None:
    for command in ("pactl", "pw-record", "pw-play"):
        require(command)
    ensure_endpoint("sinks", SINK)
    ensure_endpoint("sources", SOURCE)

    tone = make_tone()
    with tempfile.TemporaryDirectory(prefix="voxpassport-pipewire-") as temp_dir:
        capture_path = Path(temp_dir) / "capture.raw"
        record = subprocess.Popen(
            [
                "pw-record",
                "--raw",
                "--rate", str(SAMPLE_RATE),
                "--channels", str(CHANNELS),
                "--format", "s16",
                "--target", SOURCE,
                str(capture_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(0.35)
            play = subprocess.run(
                [
                    "pw-play",
                    "--raw",
                    "--rate", str(SAMPLE_RATE),
                    "--channels", str(CHANNELS),
                    "--format", "s16",
                    "--target", SINK,
                    "-",
                ],
                input=tone,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=8.0,
            )
            if play.returncode != 0:
                raise SystemExit(f"pw-play failed: {play.stderr.decode(errors='replace').strip()}")
            time.sleep(0.35)
        finally:
            record.terminate()
            try:
                _, stderr = record.communicate(timeout=3.0)
            except subprocess.TimeoutExpired:
                record.kill()
                _, stderr = record.communicate()
        if record.returncode not in (0, -15):
            raise SystemExit(f"pw-record failed: {stderr.decode(errors='replace').strip()}")

        captured = capture_path.read_bytes() if capture_path.exists() else b""

    samples = mono_samples(captured)
    rms, tone_amplitude = tone_metrics(samples)
    print(f"captured_bytes={len(captured)} rms={rms:.5f} tone_440hz={tone_amplitude:.5f}")
    if len(captured) < SAMPLE_RATE * CHANNELS * 2 // 4:
        raise SystemExit("FAIL: too little PCM was captured from VoxPassport Virtual Microphone")
    if rms < 0.01:
        raise SystemExit("FAIL: captured virtual-microphone PCM is effectively silent")
    if tone_amplitude < 0.08:
        raise SystemExit("FAIL: deterministic 440 Hz component did not cross the virtual cable")
    print("PASS: VoxPassport Translation Sink -> VoxPassport Virtual Microphone PCM bridge validated")


if __name__ == "__main__":
    main()
