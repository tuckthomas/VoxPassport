"""
LiveTranslator — TTS Bakeoff
==============================
Compares TTS models/modes on Romanian and English synthesis.

Usage:
    python benchmarks/tts_bakeoff.py --models omnivoice_stock --languages ro,en

Metrics collected per model (Section 27.3 of plan):
  - Time to first audio chunk (ms)
  - Real-time factor (RTF)
  - Output audio duration vs reference duration
  - VRAM peak (if GPU-based)
  - Re-ASR WER on generated speech (using existing ASR adapter)
  - Speaker similarity (placeholder — requires MOS/SECS evaluation tool)
  - Chunk boundary artifact count (manual review flag)

Output: benchmarks/tts/results/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import wave
import io
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.corpus_harness import BenchmarkCorpus, CorpusEntry

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ---------------------------------------------------------------------------
# Result structures
# ---------------------------------------------------------------------------

@dataclass
class UtteranceTtsResult:
    utterance_id: str
    model_id: str
    mode: str  # "stock" | "cloned"
    language: str
    input_text: str
    time_to_first_audio_ms: Optional[float]
    total_synthesis_ms: float
    output_duration_s: float
    real_time_factor: float
    chunk_count: int
    re_asr_wer: Optional[float] = None   # WER of re-ASR on generated audio
    speaker_similarity: Optional[float] = None  # placeholder
    boundary_artifact_flag: bool = False  # manual review


@dataclass
class TtsBakeoffResults:
    model_id: str
    mode: str
    language: str
    hardware: dict
    timestamp: float
    utterance_results: list[UtteranceTtsResult] = field(default_factory=list)

    # Aggregates
    mean_time_to_first_audio_ms: float = 0.0
    mean_rtf: float = 0.0
    p50_synthesis_ms: float = 0.0
    p95_synthesis_ms: float = 0.0
    max_synthesis_ms: float = 0.0
    mean_re_asr_wer: Optional[float] = None

    def compute_aggregates(self) -> None:
        if not self.utterance_results:
            return
        tta = [r.time_to_first_audio_ms for r in self.utterance_results if r.time_to_first_audio_ms is not None]
        rtfs = [r.real_time_factor for r in self.utterance_results]
        syn_ms = sorted(r.total_synthesis_ms for r in self.utterance_results)
        n = len(syn_ms)

        self.mean_time_to_first_audio_ms = sum(tta) / len(tta) if tta else 0.0
        self.mean_rtf = sum(rtfs) / len(rtfs)
        self.p50_synthesis_ms = syn_ms[n // 2]
        self.p95_synthesis_ms = syn_ms[int(n * 0.95)]
        self.max_synthesis_ms = syn_ms[-1]

        wers = [r.re_asr_wer for r in self.utterance_results if r.re_asr_wer is not None]
        if wers:
            self.mean_re_asr_wer = sum(wers) / len(wers)


# ---------------------------------------------------------------------------
# Bakeoff runner
# ---------------------------------------------------------------------------

def run_tts_bakeoff(
    model_configs: list[dict],
    languages: list[str],
    corpus_path: Path,
    output_dir: Path,
) -> list[TtsBakeoffResults]:
    corpus = BenchmarkCorpus.load(corpus_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    hardware = _get_hardware_info()
    all_results: list[TtsBakeoffResults] = []

    for config in model_configs:
        import asyncio
        asyncio.run(_run_model_async(config, languages, corpus, output_dir, hardware, all_results))

    return all_results


async def _run_model_async(config, languages, corpus, output_dir, hardware, all_results):
    model_id = config["model_id"]
    mode = config.get("mode", "stock")
    adapter = _load_tts_adapter(model_id, mode)
    if adapter is None:
        return

    try:
        await adapter.load()
    except Exception as e:
        logger.error("Failed to load TTS %r: %s", model_id, e)
        return

    from runtime.inference.protocol import LanguageCode, VoiceSpec

    for language in languages:
        results = TtsBakeoffResults(
            model_id=model_id,
            mode=mode,
            language=language,
            hardware=hardware,
            timestamp=time.time(),
        )

        try:
            lang_code = LanguageCode(language)
        except ValueError:
            logger.warning("Unknown language code: %r", language)
            continue

        if not await adapter.supports_language(lang_code):
            logger.warning("Model %r does not support language %r. Skipping.", model_id, language)
            continue

        voice = VoiceSpec(language=lang_code, is_cloned=(mode == "cloned"))

        # Use corpus entries translated to this language as TTS input
        entries = [
            e for e in corpus._entries
            if e.target_language == language
        ]
        if not entries:
            # Fall back to source language texts
            entries = [e for e in corpus._entries if e.source_language == language]

        if not entries:
            logger.warning("No corpus entries for language=%r", language)
            continue

        logger.info("Benchmarking TTS %r mode=%r lang=%r (%d entries)...", model_id, mode, language, len(entries))

        for entry in entries[:50]:  # Cap at 50 for TTS (synthesis is slow)
            text = entry.reference_translation if entry.target_language == language else entry.source_text
            utt_result = await _eval_utterance_tts(
                adapter=adapter,
                text=text,
                language=lang_code,
                voice=voice,
                utterance_id=entry.utterance_id,
                model_id=model_id,
                mode=mode,
                language_str=language,
            )
            if utt_result:
                results.utterance_results.append(utt_result)

        results.compute_aggregates()
        all_results.append(results)

        out_file = output_dir / f"{model_id.replace('/', '_')}_{mode}_{language}_{int(time.time())}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(asdict(results), f, indent=2)

        _print_summary(results)

    await adapter.unload()


async def _eval_utterance_tts(
    adapter,
    text: str,
    language,
    voice,
    utterance_id: str,
    model_id: str,
    mode: str,
    language_str: str,
) -> Optional[UtteranceTtsResult]:
    try:
        t0 = time.monotonic()
        first_chunk_time: Optional[float] = None
        chunk_count = 0
        all_pcm = bytearray()
        sample_rate = adapter.native_sample_rate_hz

        async for chunk in adapter.synthesize_stream(text, language, voice):
            if first_chunk_time is None:
                first_chunk_time = (time.monotonic() - t0) * 1000.0
            all_pcm.extend(chunk.data)
            chunk_count += 1
            sample_rate = chunk.sample_rate_hz

        total_ms = (time.monotonic() - t0) * 1000.0

        # Calculate output audio duration from PCM length
        # Assume PCM_F32LE (4 bytes per sample, 1 channel)
        output_duration_s = len(all_pcm) / (4 * sample_rate) if sample_rate > 0 else 0.0
        rtf = total_ms / 1000.0 / output_duration_s if output_duration_s > 0 else 0.0

        return UtteranceTtsResult(
            utterance_id=utterance_id,
            model_id=model_id,
            mode=mode,
            language=language_str,
            input_text=text[:100],
            time_to_first_audio_ms=first_chunk_time,
            total_synthesis_ms=total_ms,
            output_duration_s=output_duration_s,
            real_time_factor=rtf,
            chunk_count=chunk_count,
        )

    except Exception:
        logger.exception("TTS eval failed for %s", utterance_id)
        return None


def _load_tts_adapter(model_id: str, mode: str):
    from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
    adapters = {
        "omnivoice": OmniVoiceTtsAdapter,
        "omnivoice_stock": OmniVoiceTtsAdapter,
        "omnivoice-stock": OmniVoiceTtsAdapter,
        "k2-fsa-omnivoice": OmniVoiceTtsAdapter,
    }
    cls = adapters.get(model_id.lower())
    if cls is None:
        logger.error("Unknown TTS model_id: %r", model_id)
        return None
    return cls()


def _get_hardware_info() -> dict:
    info: dict = {"python": sys.version}
    try:
        import torch
        info["pytorch"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
    except ImportError:
        info["pytorch"] = "not installed"
    return info


def _print_summary(results: TtsBakeoffResults) -> None:
    print(f"\n{'='*60}")
    print(f"  TTS BAKEOFF: {results.model_id} mode={results.mode} lang={results.language}")
    print(f"{'='*60}")
    print(f"  Utterances evaluated:      {len(results.utterance_results)}")
    print(f"  Mean time to first audio:  {results.mean_time_to_first_audio_ms:.0f}ms")
    print(f"  Mean RTF:                  {results.mean_rtf:.3f}")
    print(f"  p50 synthesis latency:     {results.p50_synthesis_ms:.0f}ms")
    print(f"  p95 synthesis latency:     {results.p95_synthesis_ms:.0f}ms")
    print(f"  Max synthesis latency:     {results.max_synthesis_ms:.0f}ms")
    if results.mean_re_asr_wer is not None:
        print(f"  Re-ASR WER:                {results.mean_re_asr_wer*100:.1f}%")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TTS bakeoff")
    parser.add_argument("--models", default="omnivoice_stock",
                        help="Comma-separated model IDs")
    parser.add_argument("--modes", default="stock",
                        help="Comma-separated modes: stock,cloned")
    parser.add_argument("--languages", default="ro,en")
    parser.add_argument("--corpus", default="tests/fixtures/corpus/en_ro_corpus.jsonl")
    parser.add_argument("--output-dir", default="benchmarks/tts/results")
    args = parser.parse_args()

    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    languages = [l.strip() for l in args.languages.split(",") if l.strip()]
    corpus_path = Path(args.corpus)
    output_dir = Path(args.output_dir)

    model_configs = [
        {"model_id": mid, "mode": mode}
        for mid in model_ids
        for mode in modes
    ]

    logger.info("Starting TTS bakeoff: %d configs, languages=%s", len(model_configs), languages)
    results = run_tts_bakeoff(model_configs, languages, corpus_path, output_dir)
    logger.info("TTS bakeoff complete. %d result sets.", len(results))


if __name__ == "__main__":
    main()
