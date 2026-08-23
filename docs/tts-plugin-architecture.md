# TTS Plugin and Runtime-Profile Architecture

All local VoxPassport TTS models use one application architecture. There are no model-specific application adapters, fixed model worker ports, or native/in-process exceptions.

The boundary is intentionally split into four concerns:

1. **`ManifestTtsAdapter`** normalizes the application-side TTS contract and `voxpassport.tts.v1` transport.
2. **TTS manifests** describe the model, capabilities, driver, and logical `runtime_profile` it requires.
3. **`TtsRuntimeSupervisor`** owns process topology: interpreter selection, worker startup, dynamic localhost endpoints, health checks, model residency, crash recovery, and idle shutdown.
4. **`TtsDriver` implementations** normalize model libraries, DLLs, or external local TTS backends behind the common worker protocol.

The main daemon and orchestrator must not gain model-name branches when another local TTS model is added.

## Current topology

```text
TTS model manifest
       │
       ├── model identity / capabilities
       ├── driver entrypoint + options
       └── runtime_profile
                │
                ▼
        TtsRuntimeSupervisor
                │
        choose runtime profile
                │
      ┌─────────┴──────────┐
      ▼                    ▼
 profile: core       profile: coqui-xtts
 primary .venv       isolated profile .venv
      │                    │
      └─────────┬──────────┘
                ▼
       generic TTS host
       ephemeral 127.0.0.1 port
                │
                ▼
             TtsDriver
                │
                ▼
       model / DLL / backend
```

A model manifest answers **what runtime family does this driver require?** The supervisor answers **where is that runtime currently running?** Ephemeral worker endpoints are operational state and are never persisted as model identity.

## Directory layout

```text
runtime/
  inference/
    adapters/tts/
      manifest_tts_adapter.py
      profile_reference.py
    tts_plugins/
      manifest.py
      registry_bridge.py
      runtime_profiles.py
      runtime_supervisor.py
      runtime_status.py
      runtime_cleanup.py
  profiles/
    runtime_profiles.json
    coqui-xtts/
      pyproject.toml
      uv.lock                # generated/updated by uv sync in a connected dev environment
      .venv/                 # ignored
  tts_manifests/
    omnivoice-stock.json
    higgs-tts-3.json
    higgs-tts-3-q4_k_m.json
    moss-tts-1.5.json
    voxcpm-2.json
    xtts-v2-romanian-v2.json
  workers/
    tts_host/
      server.py
      protocol.py
      driver_loader.py
      requirements-xtts.txt  # fallback when uv is unavailable
      drivers/
        omnivoice.py
        higgs_native.py
        openai_proxy.py
        xtts_romanian.py
        xtts_runtime.py
        xtts_common.py
```

## Manifest schema

Local TTS manifests use schema version 2. A manifest contains a logical runtime profile and must **not** contain worker URLs or fixed ports.

Example:

```json
{
  "schema_version": 2,
  "model_id": "xtts-v2-romanian-v2",
  "runtime_profile": "coqui-xtts",
  "driver": {
    "entrypoint": "runtime.workers.tts_host.drivers.xtts_romanian:XttsRomanianDriver",
    "options": {}
  },
  "capabilities": {
    "languages": ["en", "ro"],
    "streaming": true,
    "voice_cloning": true,
    "cross_lingual_voice_cloning": true
  },
  "audio": {
    "sample_rate_hz": 24000,
    "sample_format": "pcm_s16le"
  }
}
```

`TtsManifest` rejects a legacy `worker` section. This prevents deployment topology from leaking back into model metadata.

A URL inside a **driver option** is different. For example, MOSS or full Higgs may proxy an already-running backend with its own API address. That URL belongs to the driver/backend contract; it is not the address of VoxPassport's generic worker process.

## Runtime profiles

Runtime profiles represent **dependency-compatible families**, not individual models.

Current profiles:

| Profile | Environment | Intended models |
| --- | --- | --- |
| `core` | primary `.venv` | OmniVoice, native Higgs, proxy drivers, and other TTS drivers compatible with the primary stack |
| `coqui-xtts` | `runtime/profiles/coqui-xtts/.venv` | XTTS/Coqui |

A new model should reuse an existing profile whenever its dependency graph is compatible. Create a new profile only when there is a genuine conflict or isolation requirement, such as a different Python version, incompatible Transformers/PyTorch constraints, native-library requirements, or deliberate fault isolation.

Do **not** create one environment per model by default.

## Why XTTS is isolated

The main VoxPassport environment currently follows Hugging Face Transformers from Git because the ASR stack can require unreleased support. Coqui XTTS constrains Transformers to the range it supports. Combining those dependency graphs would let an unrelated ASR upgrade break XTTS or force the rest of VoxPassport to remain pinned to XTTS-compatible dependencies.

The separate runtime profile is therefore intentional. What was removed is the old special-case topology where XTTS implicitly meant a dedicated fixed port.

## Runtime supervisor responsibilities

`TtsRuntimeSupervisor` owns the complete local TTS worker lifecycle:

- resolve `manifest.runtime_profile`;
- find the configured interpreter for that profile;
- start the generic worker host only when the model is actually needed;
- bind the worker to an available `127.0.0.1` port selected at runtime;
- wait for worker health;
- request `/load` for the target model and validate post-load health;
- maintain one active local TTS model across runtime profiles on constrained hardware;
- reuse one worker when switching between models in the same compatible profile;
- unload and terminate an incompatible previous profile before activating the replacement;
- roll back to the previous manifest when a replacement fails during activation;
- restart a crashed worker and retry once when failure occurs before any audio has been emitted;
- unload released models and shut idle workers down after the profile's timeout;
- terminate owned worker processes during process exit as a final cleanup safeguard.

The supervisor is model-agnostic. Its source must not contain names such as XTTS, Higgs, MOSS, OmniVoice, or VoxCPM.

## True on-demand startup

`ManifestTtsAdapter.load()` is deliberately cheap. It marks the application adapter ready but does not spawn a TTS process.

The physical worker is started by the supervisor only when:

- an explicit TTS activation performs a health check; or
- synthesis actually begins.

Therefore a `CAPTIONS_ONLY` session can start the normal inference pipeline without launching any TTS worker at all.

## Stable worker protocol

Every supervised host exposes the same local protocol:

```text
GET  /health
GET  /v1/capabilities?model_id=<id>
POST /load
POST /unload
POST /v1/audio/speech
GET  /metrics
```

A synthesis request remains model-independent:

```json
{
  "model": "xtts-v2-romanian-v2",
  "input": "Bună ziua.",
  "language": "ro",
  "response_format": "pcm",
  "ref_audio_path": "C:/.../reference.wav",
  "ref_text": "optional transcript",
  "target_conditioning_path": "C:/.../conditioning/ro.wav"
}
```

Only fields relevant to the selected profile/model are included. Streaming responses are mono signed 16-bit little-endian PCM with sample-rate/layout headers. WAV output is used for preview/export flows.

## Adding a new TTS model

### If an existing driver already fits

Add a manifest, choose an existing runtime profile, and configure the driver. No application adapter, daemon branch, fixed port, or JavaScript model-routing case should be added.

For OpenAI-style local TTS services, reuse:

```json
"driver": {
  "entrypoint": "runtime.workers.tts_host.drivers.openai_proxy:OpenAiSpeechProxyDriver",
  "options": {
    "backend_url": "http://127.0.0.1:PORT",
    "health_path": "/v1/models",
    "speech_path": "/v1/audio/speech"
  }
}
```

Full Higgs, MOSS, and VoxCPM currently share this driver despite different request conventions.

### If inference semantics are genuinely different

Add a small worker-side `TtsDriver`:

```python
class TtsDriver:
    def load(self) -> None: ...
    def unload(self) -> None: ...
    def synthesize_pcm(self, request) -> Iterator[bytes]: ...
    def capabilities(self) -> dict: ...
    def metrics(self) -> dict: ...
    def health_check(self) -> bool: ...
```

The main application still sees only `ManifestTtsAdapter`.

### If dependencies are incompatible

Add a runtime profile rather than a model-specific worker architecture. The profile declares its interpreter/provisioning metadata; the manifest references the profile by ID.

## Runtime profile provisioning

Use the generic management command:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

`coqui-xtts` is an independent uv project at `runtime/profiles/coqui-xtts/pyproject.toml`. When `uv` is available, the provisioner runs `uv sync` for that project, producing its own `.venv` and `uv.lock`. It is intentionally **not** a member of a shared uv workspace because incompatible runtime families need independent dependency resolution.

When uv is unavailable, the same profile metadata contains declarative fallback pip installation steps. `runtime/workers/tts_host/requirements-xtts.txt` exists only for that fallback.

The initial `uv.lock` must be generated/verified in an environment with package-index access. It should then be committed for reproducible installs.

## GPU residency and hot swap

The supervisor enforces one active supervised local TTS model across profiles. On a cross-profile switch it releases the old model/process before loading the new one, avoiding simultaneous TTS residency on an 8 GB-class GPU.

`ManifestTtsAdapter` still enters VoxPassport's heavyweight GPU coordinator around each actual synthesis request, so ASR and local TTS do not intentionally launch heavyweight GPU work concurrently.

Same-profile model changes reuse the existing worker process but unload the previous driver before loading the next one.

A committed synthesis request remains protected by the worker's runtime lock, so a same-host model switch waits for the utterance boundary.

## Crash recovery semantics

A worker that dies while idle or before synthesis is detected by `ensure_active()` and restarted.

If the worker disconnects **before any output audio has been emitted**, the generic adapter asks the supervisor to recreate the profile and retries the utterance once. If audio was already emitted, VoxPassport does not replay the sentence automatically because doing so could duplicate audible speech.

Activation failure is transactional: the supervisor attempts to restore the previously active TTS manifest rather than leaving the local TTS slot in a half-switched state.

## Voice profiles

Voice profiles remain model-independent:

```text
data/voice_profiles/<profile>/reference.wav
                              reference.txt       # optional unless selected model requires it
                              conditioning/ro.wav # optional derived target conditioning
```

Transcript requirements come from the selected manifest. Driver-specific conditioning is derived from these canonical assets and must not replace `reference.wav`.

## Diagnostics

`/api/resources` now includes a `tts_runtime` section with:

- active runtime profile;
- active local TTS model;
- per-profile installation state;
- running/stopped state;
- process ID;
- current ephemeral endpoint when running;
- loaded model;
- idle timeout;
- a short `/health` probe result.

The ephemeral endpoint is diagnostic state only; it is not stored in model manifests or registry identity.

Worker stdout/stderr is written under `data/logs/tts-worker-<profile>.log`.

## Validation

Runtime Integrity covers both architecture invariants and real subprocess lifecycle behavior. Tests verify:

- schema-v2 manifests contain `runtime_profile` and no worker topology;
- all local TTS models use the single application adapter;
- runtime profiles group dependency-compatible models;
- dynamic ports are supervisor-owned;
- logical adapter load does not spawn an unused worker;
- models in one profile reuse one worker process;
- cross-profile switching terminates the incompatible previous worker;
- released workers stop after their idle timeout;
- worker death during activation rolls back the previous model;
- worker death before first audio is restarted and retried;
- the supervisor contains no model-specific dispatch logic;
- the old fixed-host launcher and XTTS-specific installer remain removed.
