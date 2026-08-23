# VoxPassport Runtime Architecture

## System overview

VoxPassport is a local-first multilingual speech runtime with thin UI and conferencing layers around a hot-swappable inference pipeline.

The current system is organized into six concerns:

1. **Desktop / browser UI** — Voice Profile Studio, Live Studio, Model Settings, caption overlay, and conferencing integration.
2. **Main inference runtime** — audio capture/playback, VAD, ASR, translation, orchestration, registry, scheduling, and local APIs.
3. **Local TTS application boundary** — one `ManifestTtsAdapter` for every local TTS model.
4. **TTS model manifests + backend runtime catalog** — declarative model metadata plus reusable backend-server family definitions.
5. **TTS runtime supervisor** — dependency/profile selection, dynamic processes/endpoints, residency, hot swap, rollback, and recovery.
6. **Worker-side TTS drivers** — model/DLL/backend-specific implementations behind `voxpassport.tts.v1`.

English ↔ Romanian is the primary development and benchmark pair, but supported languages ultimately depend on the active ASR, translation, and TTS models.

## Full-duplex audio pipeline

### Outbound: local speaker → remote listener

```text
Physical Microphone
        │
        ▼
Audio Capture
        │
        ▼
VAD + Endpointing — Silero VAD v6.2.1
        │
        ▼
ASR — NVIDIA Parakeet TDT 0.6B v3
        │
        ├──────────────► Source Caption Event
        ▼
Stable-Prefix / PhraseCommitter
        │
        ▼
Translation — Xiaomi MiLMMT-46
        │
        ├──────────────► Translated Caption Event
        ▼
ManifestTtsAdapter
        │
        ▼
TTS Runtime Supervisor
        │
        ▼
voxpassport.tts.v1 → active TTS driver
        │
        ▼
Streaming PCM / Resampler / Playback
        │
        ▼
BUS_VIRTUAL_MIC → Conference Application
```

### Inbound: remote speaker → local listener

```text
Conference Output / OS Loopback
        │
        ▼
Remote Audio Capture
        │
        ▼
VAD + Endpointing
        │
        ▼
ASR — shared Parakeet model
        │
        ├──────────────► Source Caption Event
        ▼
Stable-Prefix / PhraseCommitter
        │
        ▼
Translation — shared MiLMMT model
        │
        ├──────────────► Translated Caption Event
        ▼
ManifestTtsAdapter
        │
        ▼
TTS Runtime Supervisor
        │
        ▼
voxpassport.tts.v1 → active TTS driver
        │
        ▼
BUS_LOCAL_MONITOR → Local Headphones/Speakers ONLY
```

Bidirectionality does **not** imply duplicate model weights. Both directions can share one physical ASR model, one translation model, and one active TTS model while maintaining separate queues, language state, voice conditioning, and output routing.

## Audio bus isolation

| Bus | Description |
| --- | --- |
| `BUS_PHYSICAL_MIC` | Raw capture from the local physical microphone |
| `BUS_REMOTE_CONFERENCE` | Conference output / OS loopback |
| `BUS_OUTBOUND_TRANSLATED_TTS` | Translated TTS output for the remote listener |
| `BUS_INBOUND_TRANSLATED_TTS` | Translated TTS output for the local listener |
| `BUS_VIRTUAL_MIC` | Output device consumed by conference applications |
| `BUS_LOCAL_MONITOR` | Local headphone/speaker monitoring |

Rules:

- outbound translated TTS routes to the virtual microphone;
- inbound translated TTS routes only to the local monitor;
- generated TTS must not be recaptured as fresh ASR input;
- capture/VAD can continue while heavyweight GPU inference is serialized.

## Main process and local TTS boundary

The main process does not import or construct model-specific local TTS implementations.

```text
┌──────────────────────────────────────────────────────────────┐
│                    Main VoxPassport Runtime                  │
│ VAD → ASR → Translation → ManifestTtsAdapter → Audio Output │
└─────────────────────┬────────────────────────────────────────┘
                      │ logical model request
                      ▼
┌──────────────────────────────────────────────────────────────┐
│                   TTS Runtime Supervisor                     │
│ manifest + runtime profile + optional backend runtime       │
└──────────────┬──────────────────────────────┬────────────────┘
               │ voxpassport.tts.v1           │ backend runtime
               ▼                              ▼
┌──────────────────────────────┐    ┌──────────────────────────┐
│ Generic TTS Worker Host      │    │ BackendRuntimeCatalog    │
│ model manifest → TtsDriver   │    │ reusable server family   │
└──────────────────────────────┘    └────────────┬─────────────┘
                                                ▼
                                      Managed Proxy Backend
                                      dynamic localhost port
```

`ManifestTtsAdapter` is the only local TTS application adapter. Model-specific inference behavior belongs behind `TtsDriver`.

## TTS model manifests versus backend runtimes

These are intentionally separate abstractions.

A schema-v3 **TTS model manifest** contains:

- model ID/display name/aliases;
- capabilities and language support;
- worker `runtime_profile`;
- driver entrypoint and genuinely model-specific driver options;
- optional reusable `backend_runtime` ID;
- optional model-specific `backend_args`, such as a checkpoint.

A schema-v1 **backend runtime definition** contains reusable server-family lifecycle metadata:

- stable backend runtime ID;
- backend dependency `runtime_profile`;
- reusable launch command or one family-level command override;
- accepted/required backend arguments;
- health endpoint and startup timeout;
- endpoint driver-option name;
- optional family-level non-loopback remote URL override.

Current proxy families are defined under `runtime/tts_backend_runtimes/`:

```text
higgs-openai-server
moss-openai-server
voxcpm-openai-server
```

Current direct worker models—OmniVoice, native Higgs Q4, and XTTS Romanian—do not require backend runtime definitions.

The resulting hot-swap rule is:

```text
new model using an existing backend family
    -> model manifest only

new dependency family
    -> runtime profile

new backend server family
    -> one reusable backend runtime definition

new protocol semantics
    -> reusable TtsDriver if necessary

new daemon/supervisor model branch
    -> almost never
```

## Runtime profiles and dependency isolation

A runtime profile represents a dependency-compatible family, not a model.

```text
core
  interpreter -> primary .venv

coqui-xtts
  interpreter -> runtime/profiles/coqui-xtts/.venv
```

The generic worker model manifest and its backend runtime may resolve **different runtime profiles**. This allows a future backend server to use an incompatible toolchain without forcing the proxy driver or other models into that environment.

XTTS remains isolated because Coqui and the primary ASR/runtime stack have different dependency constraints. Isolation is a dependency boundary, not a separate TTS application architecture.

## Supervisor-managed process topology

There are no fixed local TTS worker or proxy-backend ports in model manifests or `run.bat`.

For a direct/local-library driver:

```text
manifest.runtime_profile
        ↓
resolve interpreter
        ↓
start generic TTS host if needed
        ↓
allocate ephemeral localhost port
        ↓
health check
        ↓
POST /load model
```

For a model using a reusable backend runtime:

```text
manifest.backend_runtime + backend_args
        ↓
BackendRuntimeCatalog.resolve(...)
        ↓
validate argument contract
        ↓
resolve backend runtime profile
        ↓
build reusable command template + backend_args
        ↓
allocate ephemeral localhost backend port
        ↓
start + health-check backend
        ↓
inject endpoint into generic worker driver
```

Backend runtime deployment metadata is **not loaded by the worker**. The supervisor validates it and passes only ephemeral runtime driver overrides to the worker.

An explicit non-loopback backend URL can replace local backend launch for a backend family. An unmanaged loopback endpoint is rejected because it could hold local GPU memory outside supervisor ownership.

`run.bat` starts only the main inference daemon. TTS child processes exist only when needed.

## True on-demand TTS

`ManifestTtsAdapter.load()` is a cheap logical activation and does not spawn a worker.

Physical TTS processes are created only when synthesis begins or an explicit activation performs health validation. `CAPTIONS_ONLY` therefore starts without TTS process overhead.

Released managed backends are terminated immediately. Released generic workers shut down after their runtime profile's configured idle timeout.

## Hot swap and GPU residency

For a local TTS change:

1. resolve the requested model manifest;
2. validate the optional backend runtime and `backend_args`;
3. unload the previous worker-side driver;
4. terminate the previous model's managed backend process tree;
5. terminate an incompatible previous worker profile when required;
6. start/health-check the replacement backend if required;
7. start/reuse the target generic worker and inject its ephemeral backend endpoint;
8. load/health-check the target driver;
9. commit active state only after successful load;
10. on failure, restore the previous manifest/backend when possible.

Two model manifests using the same backend runtime need no new launch wiring. Their `backend_args` are substituted into the same backend family command contract.

On low-VRAM systems, actual TTS synthesis also remains coordinated with heavyweight ASR through the shared GPU inference coordinator.

## Process crash recovery

The supervisor verifies process and health state before reuse. A managed backend whose process is alive but health endpoint fails is killed and recreated.

If a generic worker disconnects during synthesis before any audio is emitted, `ManifestTtsAdapter` requests recovery and retries once. After partial audio has been emitted, VoxPassport does not replay automatically.

Process-exit cleanup terminates supervisor-owned workers and backend process trees if normal async cleanup cannot complete.

## Diagnostics

`tts_runtime` diagnostics report:

- active worker runtime profile and model;
- worker install/running state, PID, dynamic endpoint, loaded model, idle timeout, and health;
- managed backend model ID;
- backend runtime ID and backend dependency profile;
- backend PID, dynamic endpoint, health path/result, unexpected-exit state, and exit code.

Model Settings marks the active TTS runtime **broken** when either supervised layer fails.

## Voice-profile boundary

Voice profiles are engine-independent assets:

```text
data/voice_profiles/<profile>/reference.wav
                              reference.txt        # optional unless selected model requires it
                              conditioning/ro.wav  # optional derived conditioning
```

The active manifest declares whether a reference transcript is required. Model-specific conditioning must never overwrite `reference.wav`.

## Model registry

The general registry tracks install state, active slots, benchmarks, pinning, and known-good sets. Local TTS metadata is sourced from `runtime/tts_manifests` and bridged into the registry; backend runtime definitions are deployment metadata rather than separate models.

Active logical slots can point to one physical model instance.

## Runtime-profile provisioning

Use the generic manager rather than model-specific installers:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

When uv is available, isolated profiles use their own project/lock/environment. Incompatible runtime families should not be forced into one shared workspace merely to reduce environment count.

## Local control and event transport

Studio/model APIs and caption/event transport use localhost services. Supervisor-managed TTS child processes communicate over ephemeral localhost HTTP. Explicit remote inference workers/backends are separate deployment options.

## Technology stack

| Layer | Technology |
| --- | --- |
| Main inference runtime | Python 3.12 |
| ML framework | PyTorch |
| Model ecosystem | Hugging Face Transformers / Hub plus model-specific worker libraries |
| TTS process supervision | Python subprocess + psutil process-tree cleanup + aiohttp health/control |
| TTS deployment metadata | TTS model manifests + reusable backend runtime definitions + runtime profiles |
| Runtime-profile provisioning | uv when available; venv/pip fallback |
| Local APIs / TTS transport | aiohttp / HTTP |
| Caption events | WebSocket |
| Audio DSP / I/O | NumPy, SciPy, SoundFile, SoundDevice |
| Native components | Rust workspace and native CUDA/DLL integrations where required |
| Desktop/model UI | HTML/CSS/JavaScript |

## Architectural rules

1. Application business logic must not branch on local TTS model names.
2. `ManifestTtsAdapter` remains the only local TTS application adapter.
3. Model-specific TTS behavior belongs in drivers, not the daemon or UI.
4. TTS model manifests own model identity/capabilities/driver settings and reference reusable runtime IDs; they do not own process topology.
5. Backend runtime definitions own reusable backend launch/health/remote lifecycle metadata.
6. Runtime profiles own dependency-compatible environment definitions.
7. The TTS supervisor owns local process topology, endpoints, and TTS residency.
8. Model manifests never own fixed local worker/backend ports or per-model launch command environments.
9. An unmanaged loopback proxy backend is invalid.
10. Explicit non-loopback proxy endpoints are remote resources outside local GPU residency.
11. Voice profiles remain model-independent.
12. One physical model may serve multiple logical conversation directions.
13. Adding another model on a supported backend family must be manifest-only.
