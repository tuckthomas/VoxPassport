# VoxPassport Runtime Architecture

## System overview

VoxPassport is a local-first multilingual speech runtime with thin UI and conferencing layers around a hot-swappable inference pipeline.

The current system is organized into five concerns:

1. **Desktop / browser UI** — Voice Profile Studio, Live Studio, Model Settings, caption overlay, and conferencing integration.
2. **Main inference runtime** — audio capture/playback, VAD, ASR, translation, orchestration, registry, scheduling, and local APIs.
3. **Local TTS application boundary** — one `ManifestTtsAdapter` for every local TTS model.
4. **TTS runtime supervisor** — chooses dependency profile/interpreter, starts generic workers on demand, assigns ephemeral localhost endpoints, owns local TTS residency, and recovers crashed workers.
5. **Worker-side TTS drivers** — model/DLL/backend-specific implementations behind the stable `voxpassport.tts.v1` protocol.

English ↔ Romanian is the primary development and benchmark pair, but the runtime is language-pair driven. Supported languages ultimately depend on the active ASR, translation, and TTS models.

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
        │
        ▼
Stable-Prefix / PhraseCommitter
        │
        ▼
Translation — Xiaomi MiLMMT-46
        │
        ├──────────────► Translated Caption Event
        │
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
        │
        ▼
Stable-Prefix / PhraseCommitter
        │
        ▼
Translation — shared MiLMMT model
        │
        ├──────────────► Translated Caption Event
        │
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

- `BUS_OUTBOUND_TRANSLATED_TTS` → `BUS_VIRTUAL_MIC`.
- `BUS_INBOUND_TRANSLATED_TTS` → `BUS_LOCAL_MONITOR`, never the virtual microphone.
- Generated TTS must not be recaptured as fresh ASR input.
- Capture/VAD can continue while heavyweight GPU inference is serialized.

## Main process and local TTS boundary

The main process does not import or construct model-specific local TTS implementations.

```text
┌──────────────────────────────────────────────────────────────┐
│                    Main VoxPassport Runtime                  │
│                                                              │
│ VAD → ASR → Translation → ManifestTtsAdapter → Audio Output │
│                     │                                        │
│                     ├── Caption Events                       │
│                     ├── Model Registry / Hot-Swap            │
│                     └── Optional Parallel Diarization        │
└─────────────────────┬────────────────────────────────────────┘
                      │ logical model request
                      ▼
┌──────────────────────────────────────────────────────────────┐
│                   TTS Runtime Supervisor                     │
│ manifest.runtime_profile → interpreter → process → endpoint │
└─────────────────────┬────────────────────────────────────────┘
                      │ voxpassport.tts.v1
                      ▼
┌──────────────────────────────────────────────────────────────┐
│                  Generic TTS Worker Host                     │
│ manifest → TtsDriver → model library / DLL / local backend  │
└──────────────────────────────────────────────────────────────┘
```

`ManifestTtsAdapter` is the only local TTS application adapter. Model-specific behavior belongs behind the worker-side `TtsDriver` interface. TTS identity, aliases, capabilities, driver entrypoint/options, and `runtime_profile` are declared in `runtime/tts_manifests/*.json`.

Current local TTS manifests cover OmniVoice, full Higgs TTS 3, native Higgs Q4_K_M, MOSS-TTS v1.5, VoxCPM2, and XTTS-v2 Romanian v2.

## Runtime profiles and dependency isolation

A runtime profile represents a **dependency-compatible family**, not a model.

Current profiles:

```text
core
  interpreter -> primary .venv
  models/drivers compatible with the primary Python stack

coqui-xtts
  interpreter -> runtime/profiles/coqui-xtts/.venv
  XTTS/Coqui dependency family
```

XTTS is isolated because the main environment currently follows Hugging Face Transformers from Git while Coqui constrains Transformers to its supported range. Keeping these dependency graphs independent prevents TTS constraints from pinning or destabilizing ASR dependencies.

Runtime profiles are defined in `runtime/profiles/runtime_profiles.json`. The XTTS profile is also an independent uv project at `runtime/profiles/coqui-xtts/pyproject.toml`.

A new environment should be created only for a genuine dependency/native-runtime/fault-isolation boundary. VoxPassport should not create one virtual environment per model.

## Supervisor-managed worker topology

There are no fixed local TTS worker ports in model manifests or `run.bat`.

When a supervised TTS model is needed:

```text
manifest.runtime_profile
        ↓
resolve profile interpreter
        ↓
start generic TTS host if necessary
        ↓
bind available 127.0.0.1 port
        ↓
wait for /health
        ↓
POST /load target model
        ↓
validate loaded model / capabilities
        ↓
return ephemeral endpoint to ManifestTtsAdapter
```

The worker endpoint exists only as runtime state. It is visible in diagnostics while the worker is running but is not persisted as part of model identity.

`run.bat` starts the main inference daemon only. TTS workers are child processes of the supervisor and appear only when needed.

## True on-demand TTS

`ManifestTtsAdapter.load()` does not spawn a worker. It is a cheap logical adapter activation.

A worker is created when synthesis starts or when an explicit model activation performs a health validation. This means the default `CAPTIONS_ONLY` runtime can start without loading or even starting a local TTS process.

Released models are unloaded and their idle worker is terminated after the profile's configured timeout.

## Hot-swap and GPU residency

The model registry tracks active capability slots, while the TTS supervisor owns local TTS process/model residency.

For a TTS change:

1. resolve the requested manifest and `runtime_profile`;
2. if another supervised TTS model is active, unload it;
3. if the target belongs to a different profile, terminate the incompatible previous worker before starting the replacement;
4. start/reuse the target profile worker;
5. load and health-check the target driver;
6. only after success, update the active runtime/model reference;
7. on activation failure, attempt to restore the previous manifest.

Models in the same runtime profile can reuse one worker process while swapping drivers. Models in incompatible profiles do not remain resident together by accident.

On low-VRAM systems, actual TTS synthesis is also coordinated with heavyweight ASR work through the shared GPU inference coordinator. Audio capture and VAD continue while the GPU is occupied.

## Worker crash recovery

The supervisor checks that its owned child process and loaded model are still healthy before reuse.

If a worker dies while idle, the next request recreates it. If a worker disconnects during synthesis before any audio is emitted, `ManifestTtsAdapter` asks the supervisor to recreate the runtime and retries once. After partial audio has been emitted, the utterance is not automatically replayed because that could duplicate speech.

A process-exit cleanup hook terminates supervisor-owned workers if the main Python process exits before an async idle-shutdown task can complete.

## Diagnostics

The existing resource endpoint includes `tts_runtime` state. It reports:

- active runtime profile and model;
- profile installation state;
- running/stopped state;
- worker PID;
- ephemeral endpoint while running;
- loaded model;
- idle timeout;
- short worker health result.

Worker logs are written under `data/logs/tts-worker-<profile>.log`.

## Voice-profile boundary

Voice profiles are engine-independent assets:

```text
data/voice_profiles/<profile>/reference.wav
                              reference.txt        # optional unless selected model requires it
                              conditioning/ro.wav  # optional derived conditioning
```

The active manifest declares whether a reference transcript is required. Studio/manual synthesis validates that capability rather than using model-name rules.

Model-specific derived conditioning is not canonical speaker identity and must never overwrite `reference.wav`.

## Model registry

The general registry tracks install state, active slots, benchmark metadata, pinning, and known-good sets. Local TTS metadata is sourced from `runtime/tts_manifests` and bridged into the registry at startup; it is not duplicated in the general built-in catalog.

Active slots include:

```text
asr_en
asr_ro
translation_en_ro
translation_ro_en
tts_en
tts_ro
vad
```

Different logical slots may point to one physical model instance.

## Runtime-profile provisioning

Use the generic manager rather than model-specific installers:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

When uv is available, an isolated profile with `uv_project` uses its own `uv sync`, `.venv`, and lockfile. A shared uv workspace is intentionally not used for incompatible runtime families. The profile manager provides a venv/pip fallback when uv is unavailable.

## Local control and event transport

The application uses localhost services for Studio/model-management APIs and caption/event transport. Caption events are published through the local WebSocket service. Supervisor-managed TTS child processes communicate over ephemeral localhost HTTP using `voxpassport.tts.v1`.

Remote inference workers are a separate deployment option documented in `docs/remote-workers.md`.

## Technology stack

| Layer | Technology |
| --- | --- |
| Main inference runtime | Python 3.12 |
| ML framework | PyTorch |
| Model ecosystem | Hugging Face Transformers / Hub plus model-specific worker libraries |
| TTS process supervision | Python subprocess + aiohttp health/control |
| Runtime-profile provisioning | uv when available; venv/pip fallback |
| Local APIs / TTS transport | aiohttp / HTTP |
| Caption events | WebSocket |
| Audio DSP / I/O | NumPy, SciPy, SoundFile, SoundDevice |
| Native components | Rust workspace and native CUDA/DLL integrations where required |
| Desktop/model UI | HTML/CSS/JavaScript |
| Browser companion | Chrome Manifest V3 |

## Architectural rules

1. Application business logic must not branch on local TTS model names.
2. `ManifestTtsAdapter` remains the only local TTS application adapter.
3. Model-specific TTS behavior belongs in drivers, not the daemon or UI.
4. Local TTS identity/capabilities/aliases/profile requirement belong in manifests.
5. Model manifests never own VoxPassport worker ports.
6. The TTS supervisor owns worker lifecycle, endpoints, and local TTS residency.
7. Runtime profiles group dependency-compatible models; they are not one-per-model by default.
8. Voice profiles remain model-independent.
9. One physical model may serve multiple logical conversation directions.
10. GPU residency and worker lifecycle are centrally coordinated on constrained hardware.
