# XTTS-v2 Romanian Low-VRAM Voice Cloning

VoxPassport can use `eduardem/xtts-v2-romanian-v2` as an English/Romanian cloned-voice TTS engine intended for 8 GB-class GPUs. XTTS uses the same `voxpassport.tts.v1` protocol and `ManifestTtsAdapter` as every other local TTS model. Coqui-specific behavior remains entirely inside the XTTS worker-side driver.

## Why XTTS has a separate Python environment

XTTS is intentionally isolated from the primary VoxPassport Python environment.

The primary runtime currently follows Hugging Face Transformers from Git source because the active ASR stack may need unreleased model support. The XTTS/Coqui environment constrains Transformers to the version range supported by Coqui. Those are independent dependency lifecycles, and forcing them into one environment would make an ASR/Transformers upgrade capable of breaking XTTS or make XTTS constraints pin the rest of VoxPassport.

A separate virtual environment is therefore the right **dependency-isolation boundary**. It does not mean XTTS uses a different application architecture.

The current fixed-port arrangement is an intermediate implementation. The preferred future topology is a runtime-profile supervisor that launches the same generic TTS host under the required environment on demand and assigns/discovers the endpoint dynamically. See `docs/tts-plugin-architecture.md`.

## Installation

Run once from the repository root:

```bat
install_xtts_worker.bat
```

This creates `.venv-xtts`, installs the CUDA/PyTorch generation used by VoxPassport plus `coqui-tts`, and leaves the primary `.venv` unchanged.

`run.bat` currently starts two instances of the same generic TTS host implementation when XTTS is installed:

```text
primary .venv     -> http://127.0.0.1:8098
isolated XTTS env -> http://127.0.0.1:8099
```

The second host exists only to isolate Coqui's Python dependencies. The XTTS manifest currently selects port 8099 automatically.

The Romanian checkpoint is downloaded into `models/xtts-v2-romanian-v2` on first XTTS activation if it is not already present. `VOXPASSPORT_XTTS_MODEL_DIR` can point the XTTS driver at an existing local copy instead.

## Voice conditioning modes

### Ordinary zero-shot cloning

An existing VoxPassport voice profile uses:

```text
data/voice_profiles/<profile>/reference.wav
```

XTTS derives both its speaker embedding and GPT conditioning latent from that real recording. This is the baseline path and should be tested first.

XTTS does not require the reference transcript for ordinary cloning. A profile may still contain `reference.txt` because other TTS models can require it; transcript validation is driven by the selected manifest rather than a global enrollment rule.

### Cross-lingual conditioning bridge

If a real English reference preserves identity poorly when XTTS speaks Romanian, VoxPassport supports a second, derived reference:

```text
data/voice_profiles/<profile>/conditioning/ro.wav
```

The two references have different jobs:

```text
real reference.wav
    -> XTTS speaker embedding
    -> identity / timbre source

derived conditioning/ro.wav
    -> XTTS GPT conditioning latent
    -> Romanian acoustic/language conditioning
```

The derived file never replaces `reference.wav`. The real recording remains the canonical identity source.

A heavier teacher such as MOSS-TTS v1.5 can create the Romanian reference offline:

```bat
.venv\Scripts\python.exe scripts\create_xtts_target_conditioning.py <profile_id>
```

The utility explicitly unloads XTTS from the generic host on port 8099 before loading MOSS through the primary generic host on port 8098. MOSS generates a Romanian reference in the cloned voice, the resulting WAV is saved only under the profile's `conditioning` directory, and MOSS is unloaded afterward. MOSS is not required during later XTTS calls.

Use `--text` to supply a different Romanian conditioning passage. If the MOSS backend is not on the default `127.0.0.1:8096`, set `VOXPASSPORT_MOSS_TTS_URL` before starting `run.bat`; backend URLs are driver configuration rather than application-adapter parameters.

## Romanian text normalization

Romanian comma-below characters are distinct Unicode code points from legacy cedilla variants. Before XTTS tokenization VoxPassport normalizes:

```text
ş -> ș
ţ -> ț
Ş -> Ș
Ţ -> Ț
```

The XTTS driver also sets the Romanian tokenizer character limit to 250. Live text is kept in short clauses and Romanian generation receives a dynamic `max_new_tokens` limit because this fine-tune does not have a reliable explicit Romanian stop token.

## Streaming

The XTTS driver calls `inference_stream()` directly and the generic host returns 24 kHz mono PCM as chunks become available. VoxPassport does not synthesize a complete WAV and then pretend it was streamed.

Both conversation directions share the one XTTS model instance resident in the XTTS host and use different cached speaker conditioning. Two-way conversation therefore uses two logical TTS request streams, not two copies of XTTS weights.

The host serializes a committed utterance against hot-swap, while the main `ManifestTtsAdapter` holds VoxPassport's heavy-GPU coordinator for the duration of each request.

When VoxPassport switches to a different TTS model, the orchestrator unloads the prior adapter. If that prior adapter is XTTS, the XTTS host unloads the model and releases its GPU allocations before the replacement TTS model is used on the shared GPU.

Conditioning tensors are cached on CPU with a small bounded LRU cache. Updating either the canonical reference or target-language reference changes the cache key automatically.

## Current topology vs. preferred topology

The current topology is deliberately simple:

```text
main daemon
   │
   ├── ManifestTtsAdapter -> primary generic host :8098
   └── ManifestTtsAdapter -> XTTS generic host    :8099
```

This is acceptable while XTTS is the only model family that needs a conflicting dependency environment.

The preferred scalable design is:

```text
main daemon
   │
   ▼
TTS runtime supervisor
   │
   ├── runtime profile "core"       -> primary Python environment
   └── runtime profile "coqui-xtts" -> isolated XTTS environment
```

The supervisor should start the required worker on demand, assign its endpoint, enforce cross-process GPU residency, and stop idle workers. Under that design, `8099` is no longer part of XTTS's model identity; `coqui-xtts` is merely the runtime profile required by its driver.

Do **not** merge XTTS into the main environment merely to eliminate `.venv-xtts`. The better cleanup is to generalize environment isolation so it is centrally managed.

## Validation on the RTX 2070

The model's real peak VRAM and long-running allocator behavior must be measured on the target machine rather than inferred from checkpoint size. Run:

```bat
.venv\Scripts\python.exe benchmarks\xtts_romanian_soak.py <profile_id> --turns 50
```

The benchmark defaults to the XTTS-capable generic host at `http://127.0.0.1:8099`, loads `xtts-v2-romanian-v2` through `voxpassport.tts.v1`, alternates English and Romanian cloned turns, and records:

- time to first streamed audio byte;
- total synthesis latency;
- CUDA allocated memory;
- CUDA reserved memory;
- allocator growth from the first to final turn;
- peak allocated and reserved VRAM.

Reports are written under `benchmarks/xtts_romanian/results/` and ignored by Git.

## Adoption criteria

Do not replace the current TTS default solely because XTTS loads successfully. Compare at minimum:

1. English reference -> Romanian identity similarity with ordinary XTTS conditioning.
2. English reference -> Romanian identity similarity with the target-language conditioning bridge.
3. Romanian reference -> English identity similarity.
4. Romanian pronunciation/naturalness against Higgs and MOSS.
5. first-audio latency and real-time factor during bilateral use.
6. 50+ alternating turns without material VRAM growth or OOM behavior.

If the ordinary zero-shot path is already good, do not create a synthetic conditioning reference. The MOSS bridge is a fallback for the specific cross-lingual identity-retention problem, not a mandatory enrollment step.

For the generic model-integration architecture, see `docs/tts-plugin-architecture.md`.
