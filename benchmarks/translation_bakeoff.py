"""
LiveTranslator — Translation Bakeoff
======================================
Compares MT models on the EN↔RO evaluation corpus.

Usage:
    python benchmarks/translation_bakeoff.py --models milmmt_1b,milmmt_4b,riva_4b

Metrics collected per model (Section 27.2 of plan):
  - COMET / current learned semantic metric
  - chrF++ (character n-gram F-score)
  - Human adequacy score (placeholder — filled by Romanian reviewer)
  - Human fluency score (placeholder)
  - Named-entity preservation rate
  - Number/date/unit preservation rate
  - Hallucination count (flagged for manual review)
  - Omission count
  - p50 / p95 / max translation latency
  - VRAM peak

Output: benchmarks/translation/results/ + summary in docs/model-bakeoff.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
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
class UtteranceTranslationResult:
    utterance_id: str
    model_id: str
    source_language: str
    target_language: str
    source_text: str
    reference_text: str
    hypothesis_text: str
    chrf_score: float        # chrF++ approximation (no sacrebleu dependency for now)
    named_entity_hit_rate: float
    number_preservation_rate: float
    latency_ms: float
    hallucination_flag: bool = False  # flagged for manual review
    omission_flag: bool = False


@dataclass
class TranslationBakeoffResults:
    model_id: str
    source_language: str
    target_language: str
    hardware: dict
    timestamp: float
    utterance_results: list[UtteranceTranslationResult] = field(default_factory=list)

    # Aggregates
    mean_chrf: float = 0.0
    mean_named_entity_hit_rate: float = 0.0
    mean_number_preservation_rate: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    hallucination_count: int = 0
    omission_count: int = 0

    def compute_aggregates(self) -> None:
        if not self.utterance_results:
            return
        chrfs = [r.chrf_score for r in self.utterance_results]
        ne_rates = [r.named_entity_hit_rate for r in self.utterance_results]
        num_rates = [r.number_preservation_rate for r in self.utterance_results]
        latencies = sorted(r.latency_ms for r in self.utterance_results)
        n = len(latencies)

        self.mean_chrf = sum(chrfs) / len(chrfs)
        self.mean_named_entity_hit_rate = sum(ne_rates) / len(ne_rates)
        self.mean_number_preservation_rate = sum(num_rates) / len(num_rates)
        self.p50_latency_ms = latencies[n // 2]
        self.p95_latency_ms = latencies[int(n * 0.95)]
        self.max_latency_ms = latencies[-1]
        self.hallucination_count = sum(1 for r in self.utterance_results if r.hallucination_flag)
        self.omission_count = sum(1 for r in self.utterance_results if r.omission_flag)


# ---------------------------------------------------------------------------
# chrF++ approximation (character n-gram F-score)
# ---------------------------------------------------------------------------

def compute_chrf(reference: str, hypothesis: str, n: int = 6, beta: float = 2.0) -> float:
    """
    Approximate chrF++ (character n-gram F-score).
    For full chrF++ with word n-grams, use sacrebleu if available.
    """
    def get_char_ngrams(text: str, n: int) -> dict[str, int]:
        ngrams: dict[str, int] = {}
        for i in range(len(text) - n + 1):
            ng = text[i:i + n]
            ngrams[ng] = ngrams.get(ng, 0) + 1
        return ngrams

    ref_ngrams = get_char_ngrams(reference.lower(), n)
    hyp_ngrams = get_char_ngrams(hypothesis.lower(), n)

    if not ref_ngrams or not hyp_ngrams:
        return 0.0

    matches = sum(min(ref_ngrams.get(ng, 0), hyp_ngrams.get(ng, 0)) for ng in hyp_ngrams)
    precision = matches / sum(hyp_ngrams.values()) if hyp_ngrams else 0.0
    recall = matches / sum(ref_ngrams.values()) if ref_ngrams else 0.0

    if precision + recall == 0:
        return 0.0
    return (1 + beta**2) * precision * recall / (beta**2 * precision + recall)


# ---------------------------------------------------------------------------
# Named entity / number preservation
# ---------------------------------------------------------------------------

def named_entity_hit_rate(hypothesis: str, named_entities: list[str]) -> float:
    """Fraction of named entities from corpus that appear in the hypothesis."""
    if not named_entities:
        return 1.0
    hits = sum(1 for ne in named_entities if ne.lower() in hypothesis.lower())
    return hits / len(named_entities)


def number_preservation_rate(hypothesis: str, numbers: list[str]) -> float:
    """Fraction of numbers/dates/units from corpus preserved in hypothesis."""
    if not numbers:
        return 1.0
    hits = sum(1 for n in numbers if n in hypothesis)
    return hits / len(numbers)


# ---------------------------------------------------------------------------
# Hallucination / omission heuristics (flags for human review)
# ---------------------------------------------------------------------------

def _flag_hallucination(reference: str, hypothesis: str) -> bool:
    """
    Heuristic: flag if hypothesis is much longer than reference
    with very different content (rough indicator, not definitive).
    """
    ratio = len(hypothesis) / max(len(reference), 1)
    return ratio > 2.5


def _flag_omission(reference: str, hypothesis: str) -> bool:
    """Heuristic: flag if hypothesis is very short relative to reference."""
    ratio = len(hypothesis) / max(len(reference), 1)
    return ratio < 0.3


# ---------------------------------------------------------------------------
# Bakeoff runner
# ---------------------------------------------------------------------------

def run_translation_bakeoff(
    model_ids: list[str],
    directions: list[tuple[str, str]],
    corpus_path: Path,
    output_dir: Path,
) -> list[TranslationBakeoffResults]:
    corpus = BenchmarkCorpus.load(corpus_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    hardware = _get_hardware_info()
    all_results: list[TranslationBakeoffResults] = []

    for model_id in model_ids:
        adapter = _load_translation_adapter(model_id)
        if adapter is None:
            continue

        import asyncio
        asyncio.run(_run_model_async(adapter, model_id, directions, corpus, output_dir, hardware, all_results))

    return all_results


async def _run_model_async(adapter, model_id, directions, corpus, output_dir, hardware, all_results):
    try:
        await adapter.load()
    except Exception as e:
        logger.error("Failed to load %r: %s", model_id, e)
        return

    from runtime.inference.protocol import LanguageCode

    for src_lang, tgt_lang in directions:
        results = TranslationBakeoffResults(
            model_id=model_id,
            source_language=src_lang,
            target_language=tgt_lang,
            hardware=hardware,
            timestamp=time.time(),
        )

        entries = list(corpus.iter_direction(src_lang, tgt_lang))
        if not entries:
            logger.warning("No corpus entries for %s->%s", src_lang, tgt_lang)
            continue

        logger.info("Benchmarking translation %r on %s->%s (%d entries)...", model_id, src_lang, tgt_lang, len(entries))

        for entry in entries:
            try:
                src_lc = LanguageCode(src_lang)
                tgt_lc = LanguageCode(tgt_lang)
                t0 = time.monotonic()
                result = await adapter.translate(entry.source_text, src_lc, tgt_lc)
                latency_ms = (time.monotonic() - t0) * 1000.0
                hyp = result.translated_text

                utt_result = UtteranceTranslationResult(
                    utterance_id=entry.utterance_id,
                    model_id=model_id,
                    source_language=src_lang,
                    target_language=tgt_lang,
                    source_text=entry.source_text,
                    reference_text=entry.reference_translation,
                    hypothesis_text=hyp,
                    chrf_score=compute_chrf(entry.reference_translation, hyp),
                    named_entity_hit_rate=named_entity_hit_rate(hyp, entry.named_entities),
                    number_preservation_rate=number_preservation_rate(hyp, entry.numbers),
                    latency_ms=latency_ms,
                    hallucination_flag=_flag_hallucination(entry.reference_translation, hyp),
                    omission_flag=_flag_omission(entry.reference_translation, hyp),
                )
                results.utterance_results.append(utt_result)

            except Exception:
                logger.exception("Translation eval failed for %s", entry.utterance_id)

        results.compute_aggregates()
        all_results.append(results)

        out_file = output_dir / f"{model_id.replace('/', '_')}_{src_lang}_{tgt_lang}_{int(time.time())}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(asdict(results), f, indent=2)

        _print_summary(results)

    await adapter.unload()


def _load_translation_adapter(model_id: str):
    from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
    from runtime.inference.adapters.translation.riva_translate_4b_adapter import RivaTranslate4BAdapter

    adapters = {
        "milmmt_1b": lambda: MiLMMT46TranslationAdapter(model_size="1b"),
        "milmmt_4b": lambda: MiLMMT46TranslationAdapter(model_size="4b"),
        "xiaomi-milmmt-46-1b-v1.0": lambda: MiLMMT46TranslationAdapter(model_size="1b"),
        "xiaomi-milmmt-46-4b-v1.0": lambda: MiLMMT46TranslationAdapter(model_size="4b"),
        "riva_4b": RivaTranslate4BAdapter,
        "nvidia-riva-translate-4b-v2": RivaTranslate4BAdapter,
    }
    factory = adapters.get(model_id.lower())
    if factory is None:
        logger.error("Unknown translation model_id: %r", model_id)
        return None
    return factory() if callable(factory) and not isinstance(factory, type) else factory()


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


def _print_summary(results: TranslationBakeoffResults) -> None:
    print(f"\n{'='*60}")
    print(f"  MT BAKEOFF: {results.model_id} | {results.source_language}->{results.target_language}")
    print(f"{'='*60}")
    print(f"  Utterances evaluated: {len(results.utterance_results)}")
    print(f"  Mean chrF++:          {results.mean_chrf:.4f}")
    print(f"  Named entity hit:     {results.mean_named_entity_hit_rate:.4f}")
    print(f"  Number preservation:  {results.mean_number_preservation_rate:.4f}")
    print(f"  p50 latency:          {results.p50_latency_ms:.0f}ms")
    print(f"  p95 latency:          {results.p95_latency_ms:.0f}ms")
    print(f"  Max latency:          {results.max_latency_ms:.0f}ms")
    print(f"  Hallucination flags:  {results.hallucination_count}")
    print(f"  Omission flags:       {results.omission_count}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run translation bakeoff")
    parser.add_argument("--models", default="milmmt_1b,milmmt_4b,riva_4b")
    parser.add_argument("--directions", default="en-ro,ro-en",
                        help="Comma-separated language pairs, e.g. en-ro,ro-en")
    parser.add_argument("--corpus", default="tests/fixtures/corpus/en_ro_corpus.jsonl")
    parser.add_argument("--output-dir", default="benchmarks/translation/results")
    args = parser.parse_args()

    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    directions = []
    for pair in args.directions.split(","):
        pair = pair.strip()
        if "-" in pair:
            src, tgt = pair.split("-", 1)
            directions.append((src.strip(), tgt.strip()))

    corpus_path = Path(args.corpus)
    output_dir = Path(args.output_dir)

    logger.info("Starting translation bakeoff: models=%s, directions=%s", model_ids, directions)
    results = run_translation_bakeoff(model_ids, directions, corpus_path, output_dir)
    logger.info("Translation bakeoff complete. %d result sets.", len(results))


if __name__ == "__main__":
    main()
