# VoxPassport Runtime Architecture

## System overview

VoxPassport is a local-first multilingual speech platform with one canonical Expo client, a Python inference/control runtime, provider-neutral translation strategies, supervised model runtimes, and native desktop audio components.

The architecture is intentionally split by responsibility:

1. **Canonical product client** — Expo + React Native + React Native Web under `apps/client`.
2. **Integrated local runtime** — Python APIs, inference orchestration, model registry, voice profiles, strategy selection, diagnostics, and native-audio control.
3. **Translation strategies** — the modular `VAD → ASR → translation → TTS` cascade and direct speech-translation providers behind common session contracts.
4. **TTS plugin/runtime system** — model manifests, runtime profiles, reusable backend runtime families, generic worker host, and `TtsDriver` implementations.
5. **Native desktop audio** — Windows WASAPI/MMDevice, macOS CoreAudio/HAL, and Linux PipeWire/PipeWire-Pulse behind one native-media contract.
6. **Optional account service** — PostgreSQL-backed identity/provider credentials for non-local deployments; never required for local-only use.

There is no Tauri shell and no legacy HTML desktop Studio/model-manager. Desktop uses the Expo web/PWA target plus the local runtime/native audio boundary.

## Process topology

```text
┌───────────────────────────────────────────────────────────────┐
│                 Expo / React Native Web client                │
│ Translator · Models · Voice Profiles · Runtime · Settings    │
└─────────────────────────────┬─────────────────────────────────┘
                              │ typed low-frequency APIs
                              ▼
┌───────────────────────────────────────────────────────────────┐
│               VoxPassport Integrated Local Runtime            │
│ bootstrap · model registry · voice profiles · session state  │
│ strategy manager · captions · diagnostics · native routing   │
└───────────────┬─────────────────────────────┬─────────────────┘
                │                             │
                ▼                             ▼
     Modular inference cascade      Direct speech providers
     VAD → ASR → MT → TTS           provider-neutral session API
                │                             │
                └──────────────┬──────────────┘
                               ▼
                 Native desktop audio boundary
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
             Windows         macOS          Linux
          WASAPI/WDM      CoreAudio/HAL    PipeWire
```

Raw realtime PCM stays on native/subprocess paths. Expo receives state, captions, metrics, configuration, endpoint metadata, and session control—not high-frequency media frames.

## Local development services

`run.bat` starts the integrated runtime and canonical Expo web client together.

| Service | Address | Ownership |
| --- | --- | --- |
| Expo web client | `http://127.0.0.1:8081` | `apps/client` |
| Integrated runtime/API | `http://127.0.0.1:8766` | `runtime` |
| Caption WebSocket | `ws://127.0.0.1:8765/ws/captions` | runtime caption service |

TTS workers and managed TTS backends use supervisor-owned ephemeral localhost ports.

## Full-duplex translation

### Outbound: local speaker → remote listener

```text
Physical Microphone
        │
        ▼
Native Capture
        │
        ▼
VAD / Endpointing
        │
        ▼
ASR
        ├──────────────► source captions
        ▼
Translation
        ├──────────────► translated captions
        ▼
TTS / Voice Clone
        │
        ▼
Native Render
        │
        ▼
VoxPassport Translation Sink
        │
        ▼
VoxPassport Virtual Microphone
        │
        ▼
Meet / Zoom / Teams / Discord / softphone
```

### Inbound: remote speaker → local listener

```text
Conference Output / OS System Capture
        │
        ▼
Native Loopback/System Capture
        │
        ▼
VAD / Endpointing
        │
        ▼
ASR
        ├──────────────► source captions
        ▼
Translation
        ├──────────────► translated captions
        ▼
TTS / Voice Clone
        │
        ▼
Local Monitor Output
```

Both directions may share one physical ASR instance, one translation instance, and one active TTS instance while preserving independent language, queue, caption, and routing state.

## Audio bus contract

| Bus | Meaning |
| --- | --- |
| `BUS_PHYSICAL_MIC` | Local physical microphone capture |
| `BUS_REMOTE_CONFERENCE` | Conference output/system capture |
| `BUS_OUTBOUND_TRANSLATED_TTS` | Synthesized translated speech intended for remote participants |
| `BUS_INBOUND_TRANSLATED_TTS` | Synthesized translated speech intended for the local user |
| `BUS_VIRTUAL_MIC` | System microphone endpoint consumed by the conference application |
| `BUS_LOCAL_MONITOR` | Local headphones/speakers |

Routing invariants:

- outbound translated speech routes to the virtual microphone;
- inbound translated speech routes to the local monitor;
- generated TTS must not be reintroduced as fresh ASR input;
- communication platform and inference provider remain independent axes;
- capture can continue while heavyweight inference is serialized for constrained hardware.

See [`audio-routing.md`](audio-routing.md).

## Native audio service contract

Portable native audio roles are defined independently of the UI. Native helpers implement a versioned subprocess/media boundary:

```text
voxpassport.native-audio.v1
VPF1 framed PCM
```

The Python `NativeAudioBridge` discovers the platform helper, enumerates stable endpoint IDs, starts capture/render subprocesses, and exchanges bounded binary PCM frames. The live translation controller uses the same bridge/output abstractions on every desktop OS.

### Windows

Windows uses:

- MMDevice endpoint enumeration with stable IDs/friendly names/default detection;
- WASAPI physical microphone capture;
- WASAPI render-endpoint loopback capture;
- bounded WASAPI render output;
- a real WDM/WDK virtual audio device exposing:
  - `VoxPassport Translation Sink`;
  - `VoxPassport Virtual Microphone`.

The driver is derived from a pinned Microsoft Simple Audio Sample substrate. `prepare.ps1` applies guarded VoxPassport patches, preserves the Microsoft license, and creates a bounded 64 KiB render→capture PCM ring. Current GitHub Windows CI installs the WDK, compiles the kernel driver, validates/stages the INF/SYS package, and tests the Windows Rust helper.

Physical Windows installation and conferencing acceptance still require the target machine's driver policy.

### macOS

macOS uses:

- CoreAudio stable device UIDs;
- AudioQueue for ordinary physical microphone/output paths;
- macOS 14.2+ Core Audio process taps for system-audio capture;
- direct CoreAudio device I/O for the VoxPassport virtual devices;
- a real HAL `AudioServerPlugIn` using libASPL.

The HAL publishes:

- `VoxPassport Translation Sink`;
- `VoxPassport Virtual Microphone`.

The sink writes into a bounded 64 KiB PCM ring; the virtual microphone reads from the same ring. Hosted macOS CI builds and installs the HAL plug-in, restarts Core Audio, enumerates both devices, transfers deterministic PCM through the cable, verifies the expected tone, and uninstalls the plug-in. The helper also normalizes provider-shape PCM, including 24 kHz mono, to the fixed 48 kHz S16 stereo HAL format.

A physical Mac is still required for real hardware endpoints, TCC prompts, conferencing applications, and production signing/notarization.

### Linux

Linux uses:

- PipeWire/PipeWire-Pulse endpoint discovery;
- Pulse-compatible capture/render clients for exact endpoint targeting;
- physical microphone capture;
- sink-monitor system/loopback capture;
- persistent virtual endpoints created with `module-null-sink` and `module-remap-source`.

The user-facing pair is again:

- `VoxPassport Translation Sink`;
- `VoxPassport Virtual Microphone`.

A headless Ubuntu CI job starts D-Bus, PipeWire, WirePlumber, and PipeWire-Pulse, installs the virtual pair, and verifies deterministic live PCM crossover through the native helper.

## Native cable format and backpressure

The system-facing virtual cable is fixed at:

- 48 kHz;
- signed 16-bit little endian PCM;
- stereo.

Platform helpers normalize source/provider audio at the native boundary. Capture and render paths use bounded queues; stale audio is dropped rather than permitting unbounded latency growth.

## Translation strategy architecture

The modular cascade and direct speech providers are peers behind a strategy/session layer.

```text
TranslationStrategyManager
        │
        ├── modular cascade
        │     VAD → ASR → MT → TTS
        │
        └── direct provider adapter
              streaming audio/events
```

Strategy activation is transactional: a candidate is validated before becoming active, and the previous strategy is retained/restored if activation fails. Strategy/routing mutation is blocked while a live native session is active.

Google/Gemini wire behavior lives behind its adapter rather than in Expo UI code. Additional direct providers can implement the same manifest/adapter/session contracts.

## TTS application boundary

The main application does not branch on local TTS model names.

```text
Main runtime
    │
    ▼
ManifestTtsAdapter
    │
    ▼
TtsRuntimeSupervisor
    ├── generic worker host → TtsDriver
    └── optional reusable BackendRuntime
```

### TTS model manifest

A model manifest owns:

- stable model identity and aliases;
- capabilities/language support;
- worker runtime profile;
- driver entrypoint/options;
- optional reusable backend runtime ID;
- model-specific backend arguments such as a checkpoint.

### Backend runtime definition

A backend runtime owns reusable server-family lifecycle metadata:

- dependency runtime profile;
- reusable launch command/family override;
- allowed/required arguments;
- health endpoint/startup timeout;
- endpoint injection option;
- optional non-loopback remote service override.

### Runtime profile

A runtime profile owns one dependency-compatible Python/runtime environment. It is a dependency boundary, not a model or UI concept.

### Supervisor

The supervisor owns:

- dynamic localhost ports;
- process trees;
- model/backend residency;
- health checks;
- hot swap;
- rollback;
- crash recovery;
- incompatible profile termination;
- idle release.

The integration rule is therefore:

```text
new model on existing backend family  -> model manifest
new dependency family                 -> runtime profile
new backend server family             -> backend runtime definition
new protocol/model semantics          -> reusable TtsDriver
new application model branch          -> almost never
```

## Voice-profile boundary

Voice profiles are model-independent persistent assets:

```text
data/voice_profiles/<profile>/reference.wav
                              reference.txt
                              profile.json
                              translated_sample.wav   # optional preview/cache
```

The exact transcript is optional unless the selected TTS manifest declares it required. Model-specific derived state must not replace the canonical reference recording.

The Expo client owns record/stage/preview/save/activate/delete UX. The Python runtime owns normalization, persistence, synthesis, preview generation/cache, and active profile state.

## Model registry and Expo model workflows

The registry owns canonical model identity, install state, active slots, pinning, cleanup eligibility, known-good sets, and model metadata. The model-management API also owns `installable` and `installation_reason`; the Expo client does not infer these from names or repository strings.

The Expo Models & Engines screen uses typed APIs for install, progress, activation and uninstall.

## Deployment/account boundary

Local-only mode is a first-class deployment:

```env
VOXPASSPORT_LOCAL_ONLY=true
```

When local-only is enabled, accounts and hosted abuse controls are disabled. The same Expo build adapts from the runtime bootstrap capabilities.

For account-enabled deployments, the separate account service owns PostgreSQL users, rotating refresh sessions, Argon2id password hashes, encrypted provider credentials and rate controls. Account identity remains separate from the local inference daemon.

Email verification, password reset, OAuth/social login and managed cloud allocation remain explicitly deferred.

## Repository ownership

- `apps/client` — canonical product UI and client-side typed API/session state.
- `apps/browser-extension` — optional browser-specific integration only.
- `runtime` — Python inference/control/runtime ownership.
- `crates/audio-core` — portable audio contracts.
- `crates/audio-windows` — Windows WASAPI/MMDevice helper.
- `crates/audio-linux` — Linux PipeWire/Pulse-compatible helper.
- `native/macos/audio-helper` — macOS CoreAudio helper.
- `drivers/*/virtual-audio` — platform virtual-audio implementations/install tooling.
- `account_api` — optional account service.

`apps/desktop-companion` and `apps/desktop` are retired and must not be reintroduced without an explicit architecture change.

## Architectural invariants

1. `apps/client` is the one canonical product UI.
2. Desktop priority does not create a second UI framework.
3. High-frequency PCM remains off UI/REST state paths.
4. Native audio is platform-specific behind one stable media contract.
5. Communication platform and inference provider remain independent.
6. Local/self-hosted operation never requires VoxPassport-hosted infrastructure.
7. Model-specific TTS behavior belongs in manifests/drivers/backend definitions, not application branches.
8. Voice profiles remain engine-independent.
9. One physical model instance may serve multiple logical conversation directions.
10. Local TTS process topology and residency belong to the supervisor.
11. Legacy fix layers, hidden compatibility DOM state, iframe/eval bridges and duplicate desktop screens are prohibited.
12. Physical-device/conferencing validation must not be conflated with hosted CI/source validation.
