#!/usr/bin/env python3
"""Deterministic macOS HAL virtual-cable validation through the native helper."""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import threading
import time
from pathlib import Path

INPUT_RATE = 24_000
INPUT_CHANNELS = 1
OUTPUT_RATE = 48_000
OUTPUT_CHANNELS = 2
FREQ = 440.0
FRAME_MAGIC = b"VPF1"
HEADER = struct.Struct("<4sQQIHBI")
SINK_NAME = "VoxPassport Translation Sink"
MIC_NAME = "VoxPassport Virtual Microphone"


def helper_path() -> Path:
    configured = os.environ.get("VOXPASSPORT_AUDIO_HELPER", "").strip()
    candidates = [Path(configured)] if configured else []
    root = Path(__file__).resolve().parents[1]
    candidates += [
        root / "native/macos/audio-helper/.build/release/voxpassport-audio-helper",
        root / "native/macos/audio-helper/.build/debug/voxpassport-audio-helper",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit("macOS voxpassport-audio-helper is not built")


def find_endpoint(devices: list[dict], name: str, role: str) -> str:
    for item in devices:
        if item.get("name") == name and item.get("role") == role:
            return str(item["id"])
    raise SystemExit(f"{name!r} ({role}) is not installed/enumerated")


def tone_chunk(sequence: int, frames: int = 480) -> bytes:
    pcm = bytearray()
    start = sequence * frames
    for i in range(frames):
        sample = int(32767 * 0.35 * math.sin(2 * math.pi * FREQ * (start + i) / INPUT_RATE))
        pcm.extend(struct.pack("<h", sample))
    payload = bytes(pcm)
    return HEADER.pack(FRAME_MAGIC, sequence, time.monotonic_ns(), INPUT_RATE, INPUT_CHANNELS, 1, len(payload)) + payload


def read_capture(proc: subprocess.Popen[bytes], output: bytearray) -> None:
    assert proc.stdout is not None
    while len(output) < OUTPUT_RATE * OUTPUT_CHANNELS * 2 * 3:
        header = proc.stdout.read(HEADER.size)
        if len(header) != HEADER.size:
            return
        magic, _, _, rate, channels, fmt, length = HEADER.unpack(header)
        if magic != FRAME_MAGIC or rate != OUTPUT_RATE or channels != OUTPUT_CHANNELS or fmt != 1:
            return
        payload = proc.stdout.read(length)
        if len(payload) != length:
            return
        output.extend(payload)


def _window_metrics(samples: list[float]) -> tuple[float, float]:
    if not samples:
        return 0.0, 0.0
    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    s = c = 0.0
    for i, x in enumerate(samples):
        angle = 2 * math.pi * FREQ * i / OUTPUT_RATE
        s += x * math.sin(angle)
        c += x * math.cos(angle)
    amplitude = 2 * math.sqrt(s * s + c * c) / len(samples)
    return rms, amplitude


def metrics(data: bytes) -> tuple[float, float]:
    samples: list[float] = []
    frame_bytes = OUTPUT_CHANNELS * 2
    for off in range(0, len(data) - frame_bytes + 1, frame_bytes):
        left, right = struct.unpack_from("<hh", data, off)
        samples.append((left + right) / 2 / 32768.0)
    if not samples:
        return 0.0, 0.0

    window = min(len(samples), OUTPUT_RATE // 2)
    step = max(1, OUTPUT_RATE // 10)
    best_rms = 0.0
    best_amplitude = 0.0
    if len(samples) <= window:
        return _window_metrics(samples)
    for start in range(0, len(samples) - window + 1, step):
        rms, amplitude = _window_metrics(samples[start : start + window])
        if amplitude > best_amplitude:
            best_rms = rms
            best_amplitude = amplitude
    return best_rms, best_amplitude


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
    sink = find_endpoint(devices, SINK_NAME, "render_output")
    mic = find_endpoint(devices, MIC_NAME, "physical_microphone")

    capture = subprocess.Popen(
        [str(helper), "capture-mic", "--endpoint", mic, "--rate", str(OUTPUT_RATE), "--channels", str(OUTPUT_CHANNELS), "--chunk-ms", "20", "--queue", "8"],
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
            [str(helper), "render", "--endpoint", sink, "--rate", str(INPUT_RATE), "--channels", str(INPUT_CHANNELS), "--queue", "16"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert render.stdin is not None
        for sequence in range(75):
            render.stdin.write(tone_chunk(sequence))
        render.stdin.close()
        if render.wait(timeout=8) != 0:
            raise SystemExit(process_error("render helper", render))
        time.sleep(0.35)
        if capture.poll() is not None:
            raise SystemExit(process_error("capture helper", capture))
    finally:
        if capture.poll() is None:
            capture.terminate()
        try:
            capture.wait(timeout=3)
        except subprocess.TimeoutExpired:
            capture.kill(); capture.wait()
        reader.join(timeout=1)

    rms, amp = metrics(bytes(captured))
    print(
        f"input={INPUT_RATE}Hz/{INPUT_CHANNELS}ch output={OUTPUT_RATE}Hz/{OUTPUT_CHANNELS}ch "
        f"captured_bytes={len(captured)} strongest_window_rms={rms:.5f} tone_440hz={amp:.5f}"
    )
    if len(captured) < OUTPUT_RATE * OUTPUT_CHANNELS * 2 // 4:
        raise SystemExit("FAIL: too little PCM captured from VoxPassport Virtual Microphone")
    if rms < 0.01:
        raise SystemExit("FAIL: captured PCM is effectively silent")
    if amp < 0.08:
        raise SystemExit("FAIL: deterministic 440 Hz component did not cross the virtual cable")
    print("PASS: 24 kHz mono provider PCM normalized through macOS Translation Sink -> Virtual Microphone")


if __name__ == "__main__":
    main()
