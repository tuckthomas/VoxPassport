"""
LiveTranslator — Offline End-to-End Command
============================================
Runs the full pipeline offline on a WAV file:
  Input WAV → ASR → Translation → TTS → Output WAV + JSON timing trace

Usage:
    python benchmarks/offline_pipeline.py \\
        --input audio/test_en.wav \\
        --source-language en \\
        --target-language ro \\
        --output-dir benchmarks/end-to-end/results/

Output:
    results/<name>_translated.wav   — Synthesized translated speech
    results/<name>_timing.json      — Full timing trace (content-free)

This is used for:
  - Proving the pipeline works before real-time implementation
  - Quick sanity checks after model changes
  - Verifying EN→RO and RO→EN translation quality
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ---------------------------------------------------------------------------
# Timing trace (content-free)
# ---------------------------------------------------------------------------

@dataclass
class PipelineTimingTrace:
    """Content-free timing trace for a single offline pipeline run."""
    source_language: str
    target_language: str
    asr_model_id: str
    mt_model_id: str
    tts_model_id: str
    input_audio_duration_s: float
    timestamp: float = field(default_factory=time.time)

    # Stage latencies
    asr_load_ms: float = 0.0
    mt_load_ms: float = 0.0
    tts_load_ms: float = 0.0
    asr_inference_ms: float = 0.0
    mt_inference_ms: float = 0.0
    tts_inference_ms: float = 0.0
    total_pipeline_ms: float = 0.0

    # TTS output
    tts_output_duration_s: float = 0.0
    tts_chunk_count: int = 0
    tts_time_to_first_audio_ms: Optional[float] = None

    # Real-time factors
    asr_rtf: float = 0.0
    tts_rtf: float = 0.0


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def run_offline_pipeline(
    input_wav: Path,
    source_language: str,
    target_language: str,
    asr_model_id: str,
    mt_model_id: str,
    tts_model_id: str,
    output_dir: Path,
) -> PipelineTimingTrace:
    from runtime.inference.asr_types import AsrConfig, AsrStream
    from runtime.inference.protocol import (
        AudioFrame,
        LanguageCode,
        SampleFormat,
        TranscriptState,
        VoiceSpec,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_wav.stem
    t_pipeline_start = time.monotonic()

    # Read input WAV
    logger.info("Reading input: %s", input_wav)
    with wave.open(str(input_wav), "rb") as wf:
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        n_channels = wf.getnchannels()
        audio_bytes = wf.readframes(n_frames)
        audio_duration_s = n_frames / sample_rate

    trace = PipelineTimingTrace(
        source_language=source_language,
        target_language=target_language,
        asr_model_id=asr_model_id,
        mt_model_id=mt_model_id,
        tts_model_id=tts_model_id,
        input_audio_duration_s=audio_duration_s,
    )

    # Load models
    logger.info("Loading ASR model: %s", asr_model_id)
    asr_adapter = _load_asr_adapter(asr_model_id)
    t0 = time.monotonic()
    await asr_adapter.load()
    trace.asr_load_ms = (time.monotonic() - t0) * 1000.0

    logger.info("Loading MT model: %s", mt_model_id)
    mt_adapter = _load_mt_adapter(mt_model_id)
    t0 = time.monotonic()
    await mt_adapter.load()
    trace.mt_load_ms = (time.monotonic() - t0) * 1000.0

    logger.info("Loading TTS model: %s", tts_model_id)
    tts_adapter = _load_tts_adapter(tts_model_id)
    t0 = time.monotonic()
    await tts_adapter.load()
    trace.tts_load_ms = (time.monotonic() - t0) * 1000.0

    # ---- ASR ----
    logger.info("Running ASR (%s -> text)...", source_language)
    src_lc = LanguageCode(source_language)
    tgt_lc = LanguageCode(target_language)

    asr_config = AsrConfig(
        language=source_language,
        sample_rate_hz=sample_rate,
        channels=n_channels,
        enable_partials=True,
    )

    t0 = time.monotonic()
    stream = await asr_adapter.start_stream(asr_config)

    # Push all audio in one big chunk for offline mode
    frame = AudioFrame(
        stream_id=stream.stream_id,
        sequence=0,
        monotonic_timestamp_ns=time.monotonic_ns(),
        sample_rate_hz=sample_rate,
        channels=n_channels,
        sample_format=SampleFormat.PCM_S16LE,
        data=audio_bytes,
    )
    await asr_adapter.push_audio(stream, frame)
    await asr_adapter.close_stream(stream)

    # Collect final transcript
    asr_text = ""
    async for event in asr_adapter.events(stream):
        if event.state == TranscriptState.FINAL:
            asr_text = event.text
            break
        elif event.state in (TranscriptState.STABLE, TranscriptState.PARTIAL):
            asr_text = event.text  # Use latest hypothesis

    trace.asr_inference_ms = (time.monotonic() - t0) * 1000.0
    trace.asr_rtf = trace.asr_inference_ms / 1000.0 / audio_duration_s if audio_duration_s > 0 else 0.0

    logger.info("ASR result: %r (latency=%.0fms)", asr_text[:80], trace.asr_inference_ms)

    if not asr_text.strip():
        logger.warning("ASR produced empty transcript. Check model and audio.")

    # ---- MT ----
    logger.info("Running MT (%s -> %s)...", source_language, target_language)
    t0 = time.monotonic()
    mt_result = await mt_adapter.translate(asr_text, src_lc, tgt_lc)
    trace.mt_inference_ms = (time.monotonic() - t0) * 1000.0
    translated_text = mt_result.translated_text

    logger.info("MT result: %r (latency=%.0fms)", translated_text[:80], trace.mt_inference_ms)

    # ---- TTS ----
    logger.info("Running TTS (%s synthesis)...", target_language)
    voice = VoiceSpec(language=tgt_lc, is_cloned=False)
    tts_output_pcm = bytearray()
    tts_sample_rate = tts_adapter.native_sample_rate_hz

    t0 = time.monotonic()
    first_chunk_time: Optional[float] = None
    chunk_count = 0

    async for chunk in tts_adapter.synthesize_stream(translated_text, tgt_lc, voice):
        if first_chunk_time is None and chunk.data:
            first_chunk_time = (time.monotonic() - t0) * 1000.0
        tts_output_pcm.extend(chunk.data)
        chunk_count += 1
        tts_sample_rate = chunk.sample_rate_hz

    trace.tts_inference_ms = (time.monotonic() - t0) * 1000.0
    trace.tts_time_to_first_audio_ms = first_chunk_time
    trace.tts_chunk_count = chunk_count

    # Calculate output duration (f32 PCM: 4 bytes/sample, 1 channel)
    if tts_sample_rate > 0 and tts_output_pcm:
        trace.tts_output_duration_s = len(tts_output_pcm) / (4 * tts_sample_rate)
        trace.tts_rtf = trace.tts_inference_ms / 1000.0 / trace.tts_output_duration_s if trace.tts_output_duration_s > 0 else 0.0

    logger.info(
        "TTS synthesis: chunks=%d, duration=%.2fs, RTF=%.3f, time_to_first=%.0fms",
        chunk_count,
        trace.tts_output_duration_s,
        trace.tts_rtf,
        first_chunk_time or 0.0,
    )

    trace.total_pipeline_ms = (time.monotonic() - t_pipeline_start) * 1000.0

    # Write output WAV (convert f32 to s16 for compatibility)
    output_wav_path = output_dir / f"{stem}_{source_language}_to_{target_language}.wav"
    if tts_output_pcm:
        _write_wav(output_wav_path, bytes(tts_output_pcm), tts_sample_rate)
        logger.info("Written output WAV: %s", output_wav_path)
    else:
        logger.warning("No TTS audio produced (stub mode?). Output WAV not written.")

    # Write timing trace
    timing_path = output_dir / f"{stem}_{source_language}_to_{target_language}_timing.json"
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(asdict(trace), f, indent=2)
    logger.info("Written timing trace: %s", timing_path)

    # Unload models
    await asr_adapter.unload()
    await mt_adapter.unload()
    await tts_adapter.unload()

    # Print summary
    _print_summary(trace)

    return trace


def _write_wav(path: Path, f32_pcm: bytes, sample_rate: int) -> None:
    """Convert f32le PCM to s16le and write as WAV."""
    import struct
    n_samples = len(f32_pcm) // 4
    if n_samples == 0:
        return
    f32_values = struct.unpack(f"<{n_samples}f", f32_pcm)
    s16_values = [max(-32768, min(32767, int(v * 32767))) for v in f32_values]
    s16_bytes = struct.pack(f"<{n_samples}h", *s16_values)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(s16_bytes)


def _load_asr_adapter(model_id: str):
    from runtime.inference.adapters.asr.nemotron35_streaming_asr_adapter import Nemotron35StreamingAsrAdapter
    from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import ParakeetTdtV3AsrAdapter
    adapters = {
        "nemotron35": Nemotron35StreamingAsrAdapter,
        "nemotron": Nemotron35StreamingAsrAdapter,
        "parakeet": ParakeetTdtV3AsrAdapter,
    }
    cls = adapters.get(model_id.lower(), Nemotron35StreamingAsrAdapter)
    return cls()


def _load_mt_adapter(model_id: str):
    from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
    if "4b" in model_id.lower():
        return MiLMMT46TranslationAdapter(model_size="4b")
    return MiLMMT46TranslationAdapter(model_size="1b")


def _load_tts_adapter(model_id: str):
    from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
    return OmniVoiceTtsAdapter()


def _print_summary(trace: PipelineTimingTrace) -> None:
    print(f"\n{'='*60}")
    print(f"  OFFLINE PIPELINE: {trace.source_language} -> {trace.target_language}")
    print(f"{'='*60}")
    print(f"  Input duration:          {trace.input_audio_duration_s:.2f}s")
    print(f"  ASR load:                {trace.asr_load_ms:.0f}ms")
    print(f"  MT load:                 {trace.mt_load_ms:.0f}ms")
    print(f"  TTS load:                {trace.tts_load_ms:.0f}ms")
    print(f"  ASR inference:           {trace.asr_inference_ms:.0f}ms (RTF={trace.asr_rtf:.3f})")
    print(f"  MT inference:            {trace.mt_inference_ms:.0f}ms")
    print(f"  TTS synthesis:           {trace.tts_inference_ms:.0f}ms (RTF={trace.tts_rtf:.3f})")
    print(f"  TTS time to first audio: {trace.tts_time_to_first_audio_ms or 0:.0f}ms")
    print(f"  Output duration:         {trace.tts_output_duration_s:.2f}s")
    print(f"  TOTAL pipeline:          {trace.total_pipeline_ms:.0f}ms")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline end-to-end pipeline on a WAV file")
    parser.add_argument("--input", required=True, help="Input WAV file")
    parser.add_argument("--source-language", default="en", help="Source language code")
    parser.add_argument("--target-language", default="ro", help="Target language code")
    parser.add_argument("--asr-model", default="nemotron35", help="ASR model ID")
    parser.add_argument("--mt-model", default="milmmt_1b", help="MT model ID")
    parser.add_argument("--tts-model", default="omnivoice_stock", help="TTS model ID")
    parser.add_argument("--output-dir", default="benchmarks/end-to-end/results")
    args = parser.parse_args()

    input_wav = Path(args.input)
    if not input_wav.exists():
        logger.error("Input file not found: %s", input_wav)
        sys.exit(1)

    asyncio.run(run_offline_pipeline(
        input_wav=input_wav,
        source_language=args.source_language,
        target_language=args.target_language,
        asr_model_id=args.asr_model,
        mt_model_id=args.mt_model,
        tts_model_id=args.tts_model,
        output_dir=Path(args.output_dir),
    ))


if __name__ == "__main__":
    main()
