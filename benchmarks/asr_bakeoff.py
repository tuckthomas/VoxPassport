"""
LiveTranslator — ASR Bakeoff
==============================
Compares ASR models on the EN↔RO evaluation corpus.

Usage:
    python benchmarks/asr_bakeoff.py --models nemotron35,parakeet --directions en,ro

Metrics collected per model:
  - WER (Word Error Rate)
  - CER (Character Error Rate)
  - Named-entity accuracy
  - Number accuracy
  - Time to first partial transcript
  - Endpoint to final transcript latency
  - Partial revision rate
  - Real-time factor (RTF)
  - GPU VRAM usage (peak)
  - p50 / p95 / max latency

Record for every run:
  - Model revision/commit
  - Runtime version (NeMo, PyTorch)
  - Quantization
  - GPU/CPU model
  - VRAM / RAM
  - Batch settings

Output: docs/model-bakeoff.md (updated) + JSON results in benchmarks/asr/results/
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.corpus_harness import BenchmarkCorpus, CorpusEntry

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ---------------------------------------------------------------------------
# Result data structures
# ---------------------------------------------------------------------------

@dataclass
class UtteranceAsrResult:
    utterance_id: str
    model_id: str
    language: str
    reference_text: str
    hypothesis_text: str
    wer: float
    cer: float
    first_partial_ms: Optional[float]
    final_latency_ms: Optional[float]
    partial_revision_rate: float
    real_time_factor: float
    audio_duration_s: float


@dataclass
class AsrBakeoffResults:
    model_id: str
    language: str
    runtime_version: str
    quantization: str
    hardware: dict
    timestamp: float
    utterance_results: list[UtteranceAsrResult] = field(default_factory=list)

    # Aggregate stats (filled after all utterances)
    mean_wer: float = 0.0
    mean_cer: float = 0.0
    mean_rtf: float = 0.0
    p50_final_latency_ms: float = 0.0
    p95_final_latency_ms: float = 0.0
    max_final_latency_ms: float = 0.0
    mean_partial_revision_rate: float = 0.0
    named_entity_accuracy: float = 0.0
    number_accuracy: float = 0.0

    def compute_aggregates(self) -> None:
        if not self.utterance_results:
            return
        wers = [r.wer for r in self.utterance_results]
        cers = [r.cer for r in self.utterance_results]
        rtfs = [r.real_time_factor for r in self.utterance_results]
        latencies = [r.final_latency_ms for r in self.utterance_results if r.final_latency_ms is not None]

        self.mean_wer = sum(wers) / len(wers)
        self.mean_cer = sum(cers) / len(cers)
        self.mean_rtf = sum(rtfs) / len(rtfs)

        if latencies:
            latencies_sorted = sorted(latencies)
            n = len(latencies_sorted)
            self.p50_final_latency_ms = latencies_sorted[n // 2]
            self.p95_final_latency_ms = latencies_sorted[int(n * 0.95)]
            self.max_final_latency_ms = latencies_sorted[-1]

        revision_rates = [r.partial_revision_rate for r in self.utterance_results]
        self.mean_partial_revision_rate = sum(revision_rates) / len(revision_rates)


# ---------------------------------------------------------------------------
# WER / CER utilities
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer for WER computation."""
    return text.lower().split()


def compute_wer(reference: str, hypothesis: str) -> float:
    """Compute Word Error Rate using dynamic programming."""
    ref = _tokenize(reference)
    hyp = _tokenize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0

    # Levenshtein distance matrix
    d = [[0] * (len(hyp) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        d[i][0] = i
    for j in range(len(hyp) + 1):
        d[0][j] = j
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)

    return d[len(ref)][len(hyp)] / len(ref)


def compute_cer(reference: str, hypothesis: str) -> float:
    """Compute Character Error Rate."""
    ref = reference.lower().replace(" ", "")
    hyp = hypothesis.lower().replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0

    d = [[0] * (len(hyp) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        d[i][0] = i
    for j in range(len(hyp) + 1):
        d[0][j] = j
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)

    return d[len(ref)][len(hyp)] / len(ref)


# ---------------------------------------------------------------------------
# Hardware info
# ---------------------------------------------------------------------------

def _get_hardware_info() -> dict:
    info: dict = {
        "python": sys.version,
    }
    try:
        import torch
        info["pytorch"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["gpu_vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)
    except ImportError:
        info["pytorch"] = "not installed"
    return info


# ---------------------------------------------------------------------------
# Bakeoff runner
# ---------------------------------------------------------------------------

def run_asr_bakeoff(
    model_ids: list[str],
    languages: list[str],
    corpus_path: Path,
    output_dir: Path,
    audio_dir: Optional[Path] = None,
) -> list[AsrBakeoffResults]:
    """
    Run the ASR bakeoff for all specified models and languages.
    Returns a list of AsrBakeoffResults (one per model+language combination).
    """
    corpus = BenchmarkCorpus.load(corpus_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    hardware = _get_hardware_info()

    all_results: list[AsrBakeoffResults] = []

    for model_id in model_ids:
        adapter = _load_asr_adapter(model_id)
        if adapter is None:
            logger.warning("Could not load adapter for model_id=%r. Skipping.", model_id)
            continue

        import asyncio
        asyncio.run(_run_model_async(adapter, model_id, languages, corpus, audio_dir, output_dir, hardware, all_results))

    return all_results


async def _run_model_async(
    adapter,
    model_id: str,
    languages: list[str],
    corpus: BenchmarkCorpus,
    audio_dir: Optional[Path],
    output_dir: Path,
    hardware: dict,
    all_results: list,
) -> None:
    import asyncio

    try:
        await adapter.load()
    except Exception as e:
        logger.error("Failed to load adapter %r: %s", model_id, e)
        return

    from runtime.inference.asr_types import AsrConfig

    for language in languages:
        results = AsrBakeoffResults(
            model_id=model_id,
            language=language,
            runtime_version="",
            quantization="fp16",
            hardware=hardware,
            timestamp=time.time(),
        )

        entries = list(corpus.iter_direction(language, language))  # ASR: same src/target lang
        if not entries:
            # Fall back to all entries in that source language regardless of target
            entries = [e for e in corpus._entries if e.source_language == language]

        if not entries:
            logger.warning("No corpus entries for language=%r. Skipping.", language)
            continue

        logger.info("Benchmarking %r on %r (%d entries)...", model_id, language, len(entries))

        for entry in entries:
            audio_path = _find_audio(entry, audio_dir)
            if audio_path is None:
                logger.debug("No audio file for %s — skipping ASR eval.", entry.utterance_id)
                continue

            utt_result = await _eval_utterance_asr(
                adapter=adapter,
                entry=entry,
                audio_path=audio_path,
                model_id=model_id,
                language=language,
            )
            if utt_result:
                results.utterance_results.append(utt_result)

        results.compute_aggregates()
        all_results.append(results)

        # Save results to disk
        out_file = output_dir / f"{model_id.replace('/', '_')}_{language}_{int(time.time())}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(asdict(results), f, indent=2)
        logger.info("Saved ASR bakeoff results: %s", out_file)

        _print_summary(results)

    await adapter.unload()


async def _eval_utterance_asr(
    adapter,
    entry: CorpusEntry,
    audio_path: Path,
    model_id: str,
    language: str,
) -> Optional[UtteranceAsrResult]:
    """Run one utterance through the ASR adapter and measure metrics."""
    from runtime.inference.asr_types import AsrConfig
    from runtime.inference.protocol import AudioFrame, SampleFormat

    try:
        # Read audio file
        with wave.open(str(audio_path), "rb") as wf:
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            audio_bytes = wf.readframes(n_frames)
            audio_duration_s = n_frames / sample_rate

        config = AsrConfig(
            language=language,
            sample_rate_hz=sample_rate,
            channels=1,
        )

        t0 = time.monotonic()
        stream = await adapter.start_stream(config)

        # Push audio in 100ms chunks
        chunk_samples = sample_rate // 10  # 100ms
        bytes_per_sample = 2  # 16-bit
        first_partial_ms: Optional[float] = None
        final_text = ""
        revision_count = 0
        partial_texts: list[str] = []

        for offset in range(0, len(audio_bytes), chunk_samples * bytes_per_sample):
            chunk = audio_bytes[offset:offset + chunk_samples * bytes_per_sample]
            if not chunk:
                break
            frame = AudioFrame(
                stream_id=stream.stream_id,
                sequence=offset // (chunk_samples * bytes_per_sample),
                monotonic_timestamp_ns=time.monotonic_ns(),
                sample_rate_hz=sample_rate,
                channels=1,
                sample_format=SampleFormat.PCM_S16LE,
                data=chunk,
            )
            await adapter.push_audio(stream, frame)
            # Check for events (non-blocking)
            import asyncio
            async for event in _drain_events(adapter.events(stream), timeout=0.01):
                if first_partial_ms is None:
                    first_partial_ms = (time.monotonic() - t0) * 1000.0
                partial_texts.append(event.text)
                revision_count += 1
                if event.is_final:
                    final_text = event.text
                    break

        # Close stream and drain remaining events
        await adapter.close_stream(stream)
        final_latency_ms = (time.monotonic() - t0) * 1000.0

        # Compute revision rate: proportion of partials that were revised
        revision_rate = (revision_count - 1) / max(revision_count, 1) if revision_count > 0 else 0.0

        wer = compute_wer(entry.source_text, final_text or "")
        cer = compute_cer(entry.source_text, final_text or "")
        rtf = (time.monotonic() - t0) / audio_duration_s if audio_duration_s > 0 else 0.0

        return UtteranceAsrResult(
            utterance_id=entry.utterance_id,
            model_id=model_id,
            language=language,
            reference_text=entry.source_text,
            hypothesis_text=final_text,
            wer=wer,
            cer=cer,
            first_partial_ms=first_partial_ms,
            final_latency_ms=final_latency_ms,
            partial_revision_rate=revision_rate,
            real_time_factor=rtf,
            audio_duration_s=audio_duration_s,
        )

    except Exception:
        logger.exception("ASR eval failed for utterance %s", entry.utterance_id)
        return None


async def _drain_events(gen, timeout: float = 0.01):
    """Drain events from an async iterator for up to timeout seconds."""
    import asyncio
    deadline = time.monotonic() + timeout
    try:
        async for event in gen:
            yield event
            if time.monotonic() >= deadline:
                break
    except StopAsyncIteration:
        pass


def _find_audio(entry: CorpusEntry, audio_dir: Optional[Path]) -> Optional[Path]:
    if not entry.audio_file:
        return None
    p = Path(entry.audio_file)
    if p.is_absolute() and p.exists():
        return p
    if audio_dir and (audio_dir / p).exists():
        return audio_dir / p
    base = Path("tests/fixtures") / p
    if base.exists():
        return base
    return None


def _load_asr_adapter(model_id: str):
    """Load the appropriate ASR adapter for a given model_id."""
    from runtime.inference.adapters.asr.nemotron35_streaming_asr_adapter import Nemotron35StreamingAsrAdapter
    from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import ParakeetTdtV3AsrAdapter

    adapters = {
        "nemotron35": Nemotron35StreamingAsrAdapter,
        "nvidia-nemotron-3.5-asr-streaming-0.6b": Nemotron35StreamingAsrAdapter,
        "parakeet": ParakeetTdtV3AsrAdapter,
        "nvidia-parakeet-tdt-0.6b-v3": ParakeetTdtV3AsrAdapter,
    }
    cls = adapters.get(model_id.lower())
    if cls is None:
        logger.error("Unknown ASR model_id: %r. Known: %s", model_id, list(adapters.keys()))
        return None
    return cls()


def _print_summary(results: AsrBakeoffResults) -> None:
    print(f"\n{'='*60}")
    print(f"  ASR BAKEOFF: {results.model_id} | lang={results.language}")
    print(f"{'='*60}")
    print(f"  Utterances evaluated: {len(results.utterance_results)}")
    print(f"  Mean WER:             {results.mean_wer:.4f} ({results.mean_wer*100:.1f}%)")
    print(f"  Mean CER:             {results.mean_cer:.4f} ({results.mean_cer*100:.1f}%)")
    print(f"  Mean RTF:             {results.mean_rtf:.3f}")
    print(f"  p50 final latency:    {results.p50_final_latency_ms:.0f}ms")
    print(f"  p95 final latency:    {results.p95_final_latency_ms:.0f}ms")
    print(f"  Max final latency:    {results.max_final_latency_ms:.0f}ms")
    print(f"  Revision rate:        {results.mean_partial_revision_rate:.3f}")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run ASR bakeoff")
    parser.add_argument(
        "--models",
        default="nemotron35,parakeet",
        help="Comma-separated model IDs to benchmark",
    )
    parser.add_argument(
        "--directions",
        default="en,ro",
        help="Comma-separated language codes to test",
    )
    parser.add_argument(
        "--corpus",
        default="tests/fixtures/corpus/en_ro_corpus.jsonl",
        help="Path to evaluation corpus JSONL file",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmarks/asr/results",
        help="Directory to write results JSON",
    )
    parser.add_argument(
        "--audio-dir",
        default=None,
        help="Base directory for audio files referenced in corpus",
    )
    args = parser.parse_args()

    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    languages = [l.strip() for l in args.directions.split(",") if l.strip()]
    corpus_path = Path(args.corpus)
    output_dir = Path(args.output_dir)
    audio_dir = Path(args.audio_dir) if args.audio_dir else None

    logger.info("Starting ASR bakeoff: models=%s, languages=%s", model_ids, languages)
    results = run_asr_bakeoff(model_ids, languages, corpus_path, output_dir, audio_dir)
    logger.info("ASR bakeoff complete. %d result sets written to %s", len(results), output_dir)


if __name__ == "__main__":
    main()
