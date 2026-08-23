# Model Bakeoff Results & Historical Selection Snapshot

> **Historical benchmark record.** The measurements below document the environment and model paths used when these bakeoffs were run. They are not the source of truth for the current runtime architecture, dependency versions, or active model selection. Current architecture is documented in `README.md`, `docs/architecture.md`, and `docs/tts-plugin-architecture.md`; current installed/active state comes from Model Settings / Model Registry.

> The TTS integration has since been refactored. OmniVoice and every other local TTS model now run through `ManifestTtsAdapter` → `voxpassport.tts.v1` → worker-side `TtsDriver`. The quality/latency measurements below remain useful as historical model evidence, but references to the old direct integration should not be interpreted as current architecture.

## Methodology

All bakeoffs use the EN ↔ RO evaluation corpus (`tests/fixtures/corpus/en_ro_corpus.jsonl`). Models are compared on identical audio and text inputs. Results are recorded with the runtime versions, model IDs, and hardware specifications present at the time of execution.

---

## 1. Hardware & Runtime Environment at Time of Bakeoff

| Field | Specification |
| :--- | :--- |
| **GPU** | NVIDIA GeForce RTX 2070 |
| **VRAM** | 8,192 MiB GDDR6 |
| **CUDA Driver** | 591.86 (WDDM) / CUDA 13.1 |
| **PyTorch Runtime** | 2.10.0 (historical benchmark environment) |
| **Operating System** | Windows 11 AMD64 |
| **Audio Core** | WASAPI Exclusive / Shared Virtual Audio Cable |

Do not copy these versions into a new installation. The repository's current installation files define the supported runtime stack.

---

## 2. ASR Bakeoff (`benchmarks/asr_bakeoff.py` & `scripts/test_asr_live.py`)

### Evaluated Model

- **NVIDIA Parakeet TDT 0.6B v3** (`nvidia/parakeet-tdt-0.6b-v3`) — **Live Weights Evaluated**
  - Historical install path: `M:\LiveTranslator\models\nvidia-parakeet-tdt-0.6b-v3`
  - Architecture: FastConformer-TDT
  - Languages: multilingual European coverage including Romanian
  - License recorded for this run: CC-BY-4.0

### Live Evaluation Results

| Model | Evaluated Input | Load Time | Inference Latency | Real-Time Factor (RTF) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Parakeet TDT 0.6B v3** | `sample_en.wav` (3.00s @ 16kHz) | 2,972ms | ~45ms per frame | **0.015** | **Live Verified** |

**Historical selection:** Parakeet TDT 0.6B v3 was validated as a practical local ASR candidate and remains the current reference ASR in the repository documentation.

---

## 3. Translation Bakeoff (`benchmarks/translation_bakeoff.py`)

### Evaluated Model

- **Xiaomi MiLMMT-46-1B-v1.0** (`xiaomi-research/MiLMMT-46-1B-v1.0`) — **Live Weights Evaluated**
  - Historical install path: `M:\LiveTranslator\models\xiaomi-milmmt-46-1b-v1.0`
  - Architecture: Gemma-based multilingual MT
  - Languages: English and Romanian verified in this benchmark

### Evaluation Results

| Model | Direction | Mean chrF++ | Named-Entity Hit Rate | Number Preservation | Sample Translation Output | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **MiLMMT-46-1B** | **EN → RO** | **0.6239** | **96.67%** | **70.0%** | `"The project budget is two hundred fifty thousand dollars."` → `"Bugetul proiectului este de două sute cincizeci de mii de dolari."` | **Live Verified** |
| **MiLMMT-46-1B** | **RO → EN** | **0.5975** | **100.0%** | **80.0%** | `"Bună ziua, mă numesc Maria Ionescu."` → `"Good day, my name is Maria Ionescu."` | **Live Verified** |

**Historical selection:** MiLMMT-46-1B became the practical low-memory translation reference.

---

## 4. TTS Bakeoff (`benchmarks/tts_bakeoff.py` & `scripts/test_tts_live.py`)

### Evaluated Model

- **k2-fsa OmniVoice** (`k2-fsa/OmniVoice`) — **Live Weights Evaluated**
  - Historical install path: `M:\LiveTranslator\models\omnivoice-stock`
  - Evaluated for Romanian and English synthesis

### Live Evaluation Results

| Language | Test Sentence | Token Count | TTFA | RTF | Estimated Duration | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Romanian** | `"Bună ziua, ce mai faceți?"` | 11 | **85.4ms** | **0.084** | 1.72s | **Live Verified** |
| **Romanian** | `"Ședința începe la ora trei și jumătate după-amiaza."` | 23 | **85.4ms** | **0.041** | 3.52s | **Live Verified** |
| **Romanian** | `"Bugetul proiectului este de două sute cincizeci de mii de dolari."` | 23 | **85.0ms** | **0.032** | 4.48s | **Live Verified** |
| **English** | `"Good afternoon, how are you doing today?"` | 9 | **85.5ms** | **0.053** | 2.76s | **Live Verified** |

These figures describe OmniVoice model behavior observed in the historical benchmark. The current integration path is now:

```text
ManifestTtsAdapter
    -> voxpassport.tts.v1
    -> OmniVoiceDriver
    -> OmniVoice library
```

The protocol/driver refactor should not be assumed to preserve these exact latency figures without re-benchmarking.

---

## 5. Historical Voice-Cloning Comparison

| Dimension | Stock Voice Mode | Cloned Voice Mode | Historical Decision / Policy |
| :--- | :--- | :--- | :--- |
| **Time to First Audio** | ~130–140ms | ~210–250ms | Stock voice was favored for lowest latency |
| **Romanian Pronunciation** | More consistent baseline | Dependent on reference/accent and model | Fall back when cloning materially degrades pronunciation |
| **Speaker Similarity** | Generic voice | Higher identity similarity with suitable reference | Cloning requires explicit profile use |
| **Resource Footprint** | Model runtime only | Adds conditioning state | Keep conditioning bounded |

Current voice-profile architecture is engine-independent. A transcript is stored when available/needed, but transcript requirements come from the selected TTS manifest rather than from a universal cloning rule.

---

## 6. Historical End-to-End Offline Sanity Test

The following was produced by an earlier pipeline configuration and is retained only as a benchmark artifact:

```text
============================================================
  OFFLINE PIPELINE SUMMARY: en -> ro
============================================================
  Input Duration:          3.00s
  ASR Model:               nvidia-nemotron-3.5-asr-streaming-0.6b
  MT Model:                xiaomi-milmmt-46-1b-v1.0
  TTS Model:               omnivoice-stock
  Total Pipeline Runtime:  2,172ms
  Steady-State Latency:    ~380ms end-to-end
============================================================
```

That ASR/TTS combination is **not** a declaration of the present default runtime. Current reference selections are documented elsewhere and should be read from the registry/UI for a running installation.

---

## 7. Current Benchmarking Policy

Future bakeoffs should record:

- exact commit SHA;
- exact Python, PyTorch, CUDA, and model-library versions;
- active TTS manifest ID and driver;
- runtime profile/environment used by the model;
- time to first audio / first token;
- real-time factor;
- peak allocated and reserved VRAM;
- end-to-end bilateral latency;
- pronunciation/naturalness for the target language;
- speaker similarity for cloned TTS;
- whether the benchmark was stock voice, ordinary cross-lingual cloning, or derived target-language conditioning.

For XTTS specifically, use the 50-turn alternating English/Romanian soak described in `docs/xtts-romanian-low-vram.md`. For native Higgs, measure actual runtime VRAM rather than inferring memory requirements from the GGUF weight size.

A model should become the default only after current-hardware measurements support the change; historical bakeoff results are evidence, not permanent architecture or configuration.
