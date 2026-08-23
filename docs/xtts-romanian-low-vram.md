# XTTS-v2 Romanian Low-VRAM Voice Cloning

VoxPassport can use `eduardem/xtts-v2-romanian-v2` as an English/Romanian cloned-voice TTS engine intended for 8 GB-class GPUs. The integration is deliberately isolated in a separate Python worker so Coqui/XTTS dependencies cannot downgrade or otherwise disturb the primary Parakeet/Transformers runtime.

## Installation

Run once from the repository root:

```bat
install_xtts_worker.bat
```

This creates `.venv-xtts`, installs the CUDA/PyTorch generation used by VoxPassport plus `coqui-tts`, and leaves the primary `.venv` unchanged. `run.bat` starts the XTTS worker automatically when `.venv-xtts` exists.

The Romanian checkpoint is downloaded into `models/xtts-v2-romanian-v2` on first XTTS activation if it is not already present. `VOXPASSPORT_XTTS_MODEL_DIR` can point the worker at an existing local copy instead.

## Voice conditioning modes

### Ordinary zero-shot cloning

An existing VoxPassport voice profile continues to use:

```text
data/voice_profiles/<profile>/reference.wav
```

XTTS derives both its speaker embedding and GPT conditioning latent from that real recording. This is the baseline path and should be tested first.

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

The utility asks the XTTS worker to unload first, uses the existing MOSS worker at `127.0.0.1:8096` to synthesize a Romanian reference in the cloned voice, and saves the result only under the profile's `conditioning` directory. MOSS does not need to remain loaded during subsequent XTTS calls.

Use `--text` to supply a different Romanian conditioning passage and `--moss-url` if the MOSS worker uses another endpoint.

## Romanian text normalization

Romanian comma-below characters are distinct Unicode code points from legacy cedilla variants. Before XTTS tokenization VoxPassport therefore normalizes:

```text
ş -> ș
ţ -> ț
Ş -> Ș
Ţ -> Ț
```

The worker also sets the Romanian XTTS tokenizer character limit to 250. Live text is kept in short clauses and Romanian generation receives a dynamic `max_new_tokens` limit because this fine-tune does not have a reliable explicit Romanian stop token.

## Streaming

The worker calls XTTS `inference_stream()` directly and returns 24 kHz mono PCM as chunks become available. VoxPassport does not synthesize a complete WAV and then pretend it was streamed.

Only one XTTS model instance is loaded by the worker. Multiple conversation directions share that model and use different cached speaker conditioning. The worker serializes its own generation calls, while the main XTTS adapter holds VoxPassport's heavy-GPU coordinator for the duration of each request so Parakeet and XTTS do not intentionally launch heavyweight work at the same time on an 8 GB GPU.

Conditioning tensors are cached on CPU with a small bounded LRU cache. Updating either the canonical reference or target-language reference changes the cache key automatically.

## Validation on the RTX 2070

The model's real peak VRAM and long-running allocator behavior must be measured on the target machine rather than inferred from checkpoint size. Run:

```bat
.venv\Scripts\python.exe benchmarks\xtts_romanian_soak.py <profile_id> --turns 50
```

The harness alternates English and Romanian cloned turns and records:

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
