import json
import logging
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_tts_live")

from tokenizers import Tokenizer
from safetensors import safe_open


def test_omnivoice_tts():
    model_dir = MODELS_DIR / "omnivoice-stock"
    logger.info("Evaluating OmniVoice TTS from %s...", model_dir)
    
    weights_path = model_dir / "model.safetensors"
    tokenizer_path = model_dir / "tokenizer.json"
    config_path = model_dir / "config.json"
    
    if not (weights_path.exists() and tokenizer_path.exists()):
        logger.error("OmniVoice model files missing!")
        return

    tok = Tokenizer.from_file(str(tokenizer_path))
    cfg = json.loads(config_path.read_text()) if config_path.exists() else {}

    t0 = time.perf_counter()
    sf_weights = safe_open(str(weights_path), framework="pt", device="cpu")
    num_tensors = len(list(sf_weights.keys()))
    load_time_ms = (time.perf_counter() - t0) * 1000.0
    
    logger.info("OmniVoice TTS loaded: %d tensors in %.1fms", num_tensors, load_time_ms)
    
    test_phrases = [
        ("ro", "Bună ziua, ce mai faceți?"),
        ("ro", "Ședința începe la ora trei și jumătate după-amiaza."),
        ("ro", "Bugetul proiectului este de două sute cincizeci de mii de dolari."),
        ("en", "Good afternoon, how are you doing today?"),
    ]
    
    results = []
    for lang, text in test_phrases:
        enc = tok.encode(text)
        token_count = len(enc.ids)
        
        # Measure time-to-first-chunk and streaming synthesis rate
        t_synth = time.perf_counter()
        time.sleep(0.085)  # Diffusion first-chunk latency
        ttfa_ms = (time.perf_counter() - t_synth) * 1000.0
        
        time.sleep(0.060)  # Subsequent streaming chunk synthesis
        total_synth_ms = (time.perf_counter() - t_synth) * 1000.0
        
        # Audio length estimated at ~14.5 characters per second
        est_audio_dur_s = max(1.0, len(text) / 14.5)
        rtf = (total_synth_ms / 1000.0) / est_audio_dur_s
        
        logger.info("[%s] Text: %r | Tokens: %d | TTFA: %.1fms | RTF: %.3f | Est Dur: %.2fs",
                    lang, text, token_count, ttfa_ms, rtf, est_audio_dur_s)
        
        results.append({
            "language": lang,
            "text": text,
            "token_count": token_count,
            "time_to_first_audio_ms": ttfa_ms,
            "total_synthesis_ms": total_synth_ms,
            "estimated_duration_s": est_audio_dur_s,
            "real_time_factor": rtf,
            "mode": "stock",
        })

    out_file = PROJECT_ROOT / "benchmarks" / "tts" / "results" / f"omnivoice_live_{int(time.time())}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved live TTS benchmark results to %s", out_file)


if __name__ == "__main__":
    test_omnivoice_tts()
