"""
LiveTranslator — Real Model Bakeoff Runner
Runs benchmarks against physical weights installed in M:\LiveTranslator\models.
Records authentic timing, throughput, and accuracy metrics on GPU/CPU.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = PROJECT_ROOT / "packages"
MODELS_DIR = PROJECT_ROOT / "models"

if str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["HF_HOME"] = str(PROJECT_ROOT / ".cache" / "huggingface")
os.environ["TRANSFORMERS_CACHE"] = str(PROJECT_ROOT / ".cache" / "huggingface" / "transformers")
os.environ["TORCH_HOME"] = str(PROJECT_ROOT / ".cache" / "torch")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_bakeoffs")

from benchmarks.corpus_harness import BenchmarkCorpus
from runtime.inference.protocol import LanguageCode


def compute_chrf(hyp: str, ref: str) -> float:
    """Character n-gram F-score (1 to 6-grams)."""
    if not hyp or not ref:
        return 0.0
    if hyp.strip().lower() == ref.strip().lower():
        return 1.0
    
    def get_char_ngrams(s: str, n: int) -> dict[str, int]:
        ng = {}
        for i in range(len(s) - n + 1):
            sub = s[i:i+n]
            ng[sub] = ng.get(sub, 0) + 1
        return ng

    f_scores = []
    for n in range(1, 7):
        hyp_ng = get_char_ngrams(hyp.lower(), n)
        ref_ng = get_char_ngrams(ref.lower(), n)
        if not hyp_ng or not ref_ng:
            continue
        common = sum(min(count, ref_ng.get(k, 0)) for k, count in hyp_ng.items())
        hyp_tot = sum(hyp_ng.values())
        ref_tot = sum(ref_ng.values())
        prec = common / hyp_tot if hyp_tot > 0 else 0.0
        rec = common / ref_tot if ref_tot > 0 else 0.0
        f = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        f_scores.append(f)

    return sum(f_scores) / len(f_scores) if f_scores else 0.0


def run_translation_benchmarks():
    logger.info("=== Running Translation Benchmark on MiLMMT-46-1B ===")
    model_path = MODELS_DIR / "xiaomi-milmmt-46-1b-v1.0"
    if not model_path.exists():
        logger.error("MiLMMT model not found at %s", model_path)
        return

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    logger.info("Loading MiLMMT on device: %s, dtype: %s", device, dtype)

    tokenizer = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        dtype=dtype,
        device_map=device if device == "cuda" else "cpu",
        low_cpu_mem_usage=True,
    )

    corpus = BenchmarkCorpus.load(PROJECT_ROOT / "tests" / "fixtures" / "corpus" / "en_ro_corpus.jsonl")
    results = []

    for entry in corpus._entries:
        src_name = "English" if entry.source_language == "en" else "Romanian"
        tgt_name = "Romanian" if entry.target_language == "ro" else "English"
        prompt = f"Translate this from {src_name} to {tgt_name}:\n{src_name}: {entry.source_text}\n{tgt_name}:"

        t0 = time.perf_counter()
        inputs = tokenizer(prompt, return_tensors="pt")
        if device == "cuda":
            inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=60, pad_token_id=tokenizer.eos_token_id, do_sample=False)
        
        gen_tokens = out[0][inputs["input_ids"].shape[1]:]
        hypothesis = tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()
        lat_ms = (time.perf_counter() - t0) * 1000.0
        chrf = compute_chrf(hypothesis, entry.reference_translation)

        logger.info("[%s] In: %r -> Out: %r (Ref: %r) | chrF: %.3f | Latency: %.1fms",
                    entry.utterance_id, entry.source_text, hypothesis, entry.reference_translation, chrf, lat_ms)

        results.append({
            "utterance_id": entry.utterance_id,
            "source_language": entry.source_language,
            "target_language": entry.target_language,
            "source_text": entry.source_text,
            "hypothesis": hypothesis,
            "reference": entry.reference_translation,
            "chrf": chrf,
            "latency_ms": lat_ms,
        })

    out_file = PROJECT_ROOT / "benchmarks" / "translation" / "results" / f"milmmt_1b_live_{int(time.time())}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved live MT results to %s", out_file)


if __name__ == "__main__":
    run_translation_benchmarks()
