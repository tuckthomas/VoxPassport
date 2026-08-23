# VoxPassport Runtime Architecture

## System overview

VoxPassport is a local-first multilingual speech runtime with thin UI and conferencing layers around a hot-swappable inference pipeline.

The current system is organized into four concerns:

1. **Desktop / browser UI** — Voice Profile Studio, Live Studio, Model Settings, caption overlay, and conferencing integration.
2. **Main inference runtime** — audio capture/playback, VAD, ASR, translation, orchestration, model registry, scheduling, and local APIs.
3. **Local TTS protocol layer** — one application-side `ManifestTtsAdapter` speaking `voxpassport.tts.v1` to generic TTS worker hosts.
4. **TTS driver runtimes** — worker-side model implementations such as OmniVoice, native Higgs, XTTS, or reusable HTTP proxy integrations.

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
voxpassport.tts.v1 → active TTS worker-side driver
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
voxpassport.tts.v1 → active TTS worker-side driver
        │
        ▼
BUS_LOCAL_MONITOR → Local Headphones/Speakers ONLY
```

Bidirectionality does **not** imply duplicate model weights. Both directions can share one physical ASR model, one translation model, and one active TTS model while maintaining separate per-direction queues, language state, voice-profile conditioning, and output routing.

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
                      │ voxpassport.tts.v1
                      ▼
┌──────────────────────────────────────────────────────────────┐
│                  Generic TTS Worker Host                     │
│                                                              │
│ manifest → TtsDriver → model library / DLL / local backend  │
└──────────────────────────────────────────────────────────────┘
```

`ManifestTtsAdapter` is the only local TTS application adapter. Model-specific code belongs behind the worker-side `TtsDriver` interface. TTS identity, aliases, capabilities, driver entrypoints, and registry metadata are declared in `runtime/tts_manifests/*.json`.

Current local TTS manifests cover:

- OmniVoice;
- Higgs TTS 3;
- native Higgs Q4_K_M / `audiocpp_engine.dll`;
- MOSS-TTS v1.5;
- VoxCPM2;
- XTTS-v2 Romanian v2.

See `docs/tts-plugin-architecture.md` for the protocol and driver contract.

## Dependency isolation

Some model libraries have incompatible or high-risk Python dependency constraints. XTTS/Coqui is currently isolated from the primary Parakeet/Transformers environment for that reason.

Current launcher topology:

```text
.venv       → generic TTS host on 127.0.0.1:8098
.venv-xtts  → same generic TTS host on 127.0.0.1:8099, when installed
main daemon → runtime/inference/server/main.py
```

This is **process/environment isolation, not a second TTS architecture**. Both hosts run the same server implementation and expose the same `voxpassport.tts.v1` protocol.

The primary runtime currently follows Hugging Face Transformers from Git source, while the XTTS environment constrains Transformers to the range supported by Coqui. Keeping those dependency graphs separate prevents a TTS package constraint from pinning or destabilizing ASR/translation dependencies.

### Recommended topology evolution

The separate environment is the correct isolation primitive, but fixed per-model ports are not the ideal long-term orchestration mechanism.

The preferred future design is a **runtime-profile supervisor**:

```text
TTS manifest
  ├── model / driver / capabilities
  └── runtime_profile: core | coqui-xtts | other isolated profile
                         │
                         ▼
                 TTS Runtime Supervisor
                    ├── choose interpreter/environment
                    ├── start generic host on demand
                    ├── assign/discover endpoint
                    ├── health-check and load driver
                    ├── enforce GPU residency policy
                    └── stop idle/incompatible workers
```

Under that design, deployment details such as `:8098` and `:8099` stop being intrinsic model metadata. Manifests describe *what the model needs*; the supervisor decides *where and how its worker runs*.

Runtime profiles should be grouped by **dependency compatibility**, not one environment per model. Models that safely share the primary environment should continue sharing it. A separate environment is warranted only when dependency constraints, native libraries, Python versions, or fault isolation justify it.

For the current early-stage codebase, the two-host implementation is a reasonable intermediate state. The next architectural improvement should be generalizing it into supervisor-managed runtime profiles, not collapsing XTTS back into the main environment.

## Hot-swap and GPU residency

The model registry tracks active capability slots. For TTS:

1. resolve the requested model through its manifest;
2. construct one `ManifestTtsAdapter`;
3. load the target worker-side driver;
4. health-check the target;
5. switch the active pipeline reference;
6. unload the previous adapter/driver when no longer shared.

A committed utterance is not interrupted by a same-host driver swap. Cross-host TTS switches also unload the previous model so an isolated XTTS process does not silently keep GPU memory resident after a primary-host model becomes active.

On low-VRAM systems, heavyweight TTS requests are coordinated with heavyweight ASR work so they do not intentionally execute concurrently on the same GPU. Audio capture and VAD continue while the GPU is occupied.

## Voice-profile boundary

Voice profiles are engine-independent assets:

```text
data/voice_profiles/<profile>/reference.wav
                              reference.txt        # optional unless model requires it
                              conditioning/ro.wav  # optional derived conditioning
```

The active manifest declares whether a reference transcript is required. Studio/manual synthesis must therefore validate transcript requirements from capabilities rather than using model-name rules.

Model-specific derived conditioning is not the canonical speaker identity and must never overwrite `reference.wav`.

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

Different logical slots may point to the same physical model instance.

## Local control and event transport

The current application uses localhost services for Studio/model-management APIs and caption/event transport. Caption events are published through the local WebSocket service. TTS workers use localhost HTTP via `voxpassport.tts.v1`.

Remote inference workers are a separate deployment option and are documented in `docs/remote-workers.md`.

## Technology stack

| Layer | Technology |
| --- | --- |
| Main inference runtime | Python 3.12 |
| ML framework | PyTorch |
| Model ecosystem | Hugging Face Transformers / Hub, plus model-specific worker libraries |
| Local APIs / TTS worker transport | aiohttp / HTTP |
| Caption events | WebSocket |
| Audio DSP / I/O | NumPy, SciPy, SoundFile, SoundDevice |
| Native components | Rust workspace and native CUDA/DLL integrations where required |
| Desktop/model UI | HTML/CSS/JavaScript with desktop companion assets |
| Browser companion | Chrome Manifest V3 |

## Architectural rules

1. Application business logic must not branch on local TTS model names.
2. `ManifestTtsAdapter` remains the only local TTS application adapter.
3. Model-specific TTS behavior belongs in drivers, not the daemon or UI.
4. Local TTS identity/capabilities/aliases belong in manifests, not duplicate catalogs.
5. Dependency isolation is allowed and encouraged when needed, but all local workers expose the same protocol.
6. Voice profiles remain model-independent.
7. One physical model may serve multiple logical conversation directions.
8. GPU residency and worker lifecycle must be centrally coordinated on constrained hardware.
