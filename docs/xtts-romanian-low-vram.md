# XTTS-v2 Romanian Low-VRAM Voice Cloning

VoxPassport can use `eduardem/xtts-v2-romanian-v2` as an English/Romanian cloned-voice TTS candidate for 8 GB-class GPUs. XTTS uses the same `ManifestTtsAdapter`, `voxpassport.tts.v1` protocol, generic worker host, and runtime supervisor as every other local TTS model. Coqui-specific behavior remains inside the XTTS driver.

## Runtime profile

XTTS declares:

```json
"runtime_profile": "coqui-xtts"
```

It does **not** declare a localhost worker port.

The supervisor resolves `coqui-xtts` to its isolated interpreter, starts the generic TTS host on an available `127.0.0.1` port when XTTS is actually needed, loads the XTTS driver, and releases the worker when it becomes idle or another incompatible TTS runtime becomes active.

Current isolated environment path:

```text
runtime/profiles/coqui-xtts/.venv
```

That environment is a dependency boundary, not a separate VoxPassport architecture.

## Why XTTS is isolated

The primary VoxPassport environment currently follows Hugging Face Transformers from Git because the ASR stack can require unreleased model support. Coqui XTTS constrains Transformers to the range it supports. Those dependency lifecycles should not be forced into one Python environment.

Keeping the dependencies separate prevents an ASR/Transformers update from breaking XTTS and prevents XTTS from pinning the rest of VoxPassport to an older dependency graph.

## Installation

The old model-specific `install_xtts_worker.bat` has been removed. Provision XTTS through the generic runtime-profile manager:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
```

To recreate a damaged environment:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

The profile is an independent uv project at:

```text
runtime/profiles/coqui-xtts/pyproject.toml
```

When `uv` is installed, the manager uses `uv sync`, which creates the profile-local `.venv` and generates/updates `uv.lock`. The lockfile should be committed after it is generated in a connected development environment.

If uv is unavailable, the manager falls back to ordinary venv/pip provisioning using the declarative steps in `runtime/profiles/runtime_profiles.json` and `runtime/workers/tts_host/requirements-xtts.txt`.

The Romanian checkpoint is downloaded into `models/xtts-v2-romanian-v2` on first XTTS model load if it is not already present. `VOXPASSPORT_XTTS_MODEL_DIR` can point the driver at an existing local copy instead.

## Startup behavior

`run.bat` starts only the main VoxPassport daemon. It does not start a primary TTS host or an XTTS host.

`ManifestTtsAdapter.load()` is a cheap logical activation. The `coqui-xtts` worker is spawned only when:

- XTTS is explicitly activated and health-validated; or
- synthesis actually starts.

A captions-only session therefore does not launch XTTS just because it is the selected/default TTS model.

## Voice conditioning modes

### Ordinary zero-shot cloning

An existing VoxPassport voice profile uses:

```text
data/voice_profiles/<profile>/reference.wav
```

XTTS derives both its speaker embedding and GPT conditioning latent from that real recording. This is the baseline path and should be tested first.

XTTS does not require the reference transcript for ordinary cloning. A profile may still contain `reference.txt` because other TTS models can require it; transcript validation is capability-driven.

### Cross-lingual conditioning bridge

If a real English reference preserves identity poorly when XTTS speaks Romanian, VoxPassport supports an optional derived Romanian conditioning reference:

```text
data/voice_profiles/<profile>/conditioning/ro.wav
```

The two references have different jobs:

```text
real reference.wav
    -> XTTS speaker embedding
    -> canonical speaker identity / timbre

derived conditioning/ro.wav
    -> XTTS GPT conditioning latent
    -> Romanian acoustic/language conditioning
```

The derived file never replaces `reference.wav`.

A heavier teacher such as MOSS-TTS v1.5 can generate the Romanian reference offline:

```bat
.venv\Scripts\python.exe scripts\create_xtts_target_conditioning.py <profile_id>
```

The utility no longer knows anything about XTTS/MOSS worker ports. It asks the runtime supervisor to activate the MOSS manifest. The supervisor evicts any incompatible active TTS runtime first, supplies the teacher's ephemeral worker endpoint, and releases MOSS after the conditioning WAV is written.

Use `--text` to provide a different Romanian conditioning passage. A true MOSS backend URL, if externally configured, remains a driver option such as `VOXPASSPORT_MOSS_TTS_URL`; that is distinct from VoxPassport worker topology.

## Romanian text normalization

Before XTTS tokenization VoxPassport normalizes legacy Romanian cedilla characters to comma-below forms:

```text
ş -> ș
ţ -> ț
Ş -> Ș
Ţ -> Ț
```

The XTTS driver also sets the Romanian tokenizer character limit to 250. Live text is kept in short clauses and Romanian generation receives a dynamic `max_new_tokens` limit because this fine-tune does not have a reliable explicit Romanian stop token.

## Streaming and shared model use

The XTTS driver calls `inference_stream()` directly and returns 24 kHz mono PCM as chunks become available. VoxPassport does not synthesize a complete WAV and then simulate streaming.

Both conversation directions share one XTTS model instance and use different cached speaker conditioning. Bilateral translation therefore uses two logical request streams, not two copies of XTTS weights.

The generic worker serializes a committed utterance against a model swap. `ManifestTtsAdapter` also holds VoxPassport's heavyweight GPU coordinator during actual synthesis so ASR and XTTS do not intentionally launch heavyweight GPU work simultaneously on an 8 GB GPU.

Conditioning tensors are cached on CPU with a bounded LRU cache. Updating the canonical reference or target-language conditioning reference changes the cache key automatically.

## Worker recovery

If the XTTS worker exits while idle, the supervisor recreates the `coqui-xtts` worker when XTTS is next needed.

If the worker disconnects during synthesis **before any audio has been emitted**, the generic adapter restarts the runtime profile and retries the utterance once. VoxPassport does not automatically replay a sentence after partial audio was already delivered because that could duplicate audible speech.

## Validation on the RTX 2070

The model's real peak VRAM and long-running allocator behavior must be measured on the target machine rather than inferred from checkpoint size.

Run:

```bat
.venv\Scripts\python.exe benchmarks\xtts_romanian_soak.py <profile_id> --turns 50
```

The benchmark resolves XTTS through its manifest and runtime profile. There is no `--endpoint` argument and no fixed-port assumption. It alternates English and Romanian cloned turns and records:

- time to first streamed audio byte;
- total synthesis latency;
- CUDA allocated memory;
- CUDA reserved memory;
- allocator growth from the first to final turn;
- peak allocated and reserved VRAM.

Reports are written under `benchmarks/xtts_romanian/results/` and ignored by Git.

## Adoption criteria

Do not replace the current TTS default solely because XTTS loads successfully. Compare at minimum:

1. English reference → Romanian identity similarity with ordinary XTTS conditioning.
2. English reference → Romanian identity similarity with the target-language conditioning bridge.
3. Romanian reference → English identity similarity.
4. Romanian pronunciation/naturalness against Higgs and MOSS.
5. first-audio latency and real-time factor during bilateral use.
6. 50+ alternating turns without material VRAM growth or OOM behavior.

If ordinary zero-shot conditioning already works well, do not create a synthetic conditioning reference. The MOSS bridge is a fallback for cross-lingual identity retention, not a mandatory enrollment step.

For the shared architecture, see `docs/tts-plugin-architecture.md`.
