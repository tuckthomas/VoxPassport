# Repository Layout and Ownership

This document is the routing map for human and AI developers. Put behavior in the directory that owns the behavior. Do not preserve obsolete implementation history as compatibility layers, duplicate screens, or patch files.

## Canonical top-level ownership

```text
VoxPassport/
├── apps/
│   ├── client/                    Canonical Expo + React Native + React Native Web product UI
│   └── browser-extension/         Optional browser-specific integration only
├── runtime/                       Python inference/runtime/control plane
├── crates/
│   ├── audio-core/                Portable native audio contracts
│   ├── audio-windows/             Windows WASAPI/MMDevice implementation
│   └── audio-linux/               Linux PipeWire/Pulse-compatible implementation
├── native/
│   └── macos/audio-helper/        macOS CoreAudio native helper
├── drivers/
│   ├── windows/virtual-audio/     WDM/WDK virtual sink + microphone
│   ├── macos/virtual-audio/       HAL AudioServerPlugIn virtual pair
│   └── linux/virtual-audio/       PipeWire-Pulse virtual pair configuration
├── account_api/                   Optional PostgreSQL account service
├── configs/                       User/operator configuration
├── tests/                         Runtime/integration/architecture tests
├── benchmarks/                    Reproducible model/runtime benchmarks
├── scripts/                       Developer/admin/validation utilities
├── docs/                          Architecture, operations and development documentation
└── .agents/plans/                 Pending/in-progress/completed implementation plans
```

There is deliberately no canonical `apps/desktop`, `apps/desktop-companion`, or other second product shell. `apps/client` is the product UI on Android, iOS, web/PWA, and desktop-oriented workflows.

## `apps/client` — canonical product UI

`apps/client` owns:

- Expo Router routes;
- React Native/React Native Web screens;
- presentation state;
- typed runtime/account API clients;
- runtime target selection;
- client-side settings;
- microphone recording UX for voice enrollment where Expo supports it;
- low-frequency live-session/model/voice/runtime control state;
- canonical brand assets under `apps/client/assets`.

It must not own:

- Python model/runtime process lifecycle;
- CUDA/model-library implementation details;
- WASAPI/CoreAudio/PipeWire internals;
- virtual-audio drivers;
- high-frequency PCM processing;
- model-name-specific process routing;
- provider wire protocols;
- iframe/eval bridges;
- fetch monkey-patches;
- Tauri IPC/dependencies;
- legacy `*-fixes.*` or `*-patch.*` layers.

Raw realtime PCM must stay out of React state and REST JSON/base64 paths.

## Desktop use of Expo

Desktop is an immediate workflow priority without a separate UI architecture.

`run.bat` starts:

```text
Integrated runtime/API     http://127.0.0.1:8766
Canonical Expo web client  http://127.0.0.1:8081
```

Desktop-native capabilities—physical capture, system/loopback capture, endpoint enumeration, translated-audio render, and virtual microphone routing—live behind local runtime/native service contracts.

The Expo client configures and observes those capabilities through typed APIs. It does not embed a native audio engine or a second desktop shell.

## `apps/browser-extension` — optional browser integration

The browser extension owns only browser-specific overlays/integration. It is not the core audio transport and must not become a duplicate inference/client application.

Core conferencing audio remains OS-native and communication-platform independent.

## Retired desktop surfaces

The following architectures are intentionally retired and must not return without an explicit architecture decision:

- `apps/desktop-companion`;
- the prototype HTML Studio/model-manager;
- duplicate desktop overlay code;
- `runtime-fixes.js`;
- `engine-catalog-fixes.js`;
- `stack-upgrade-fixes.js`;
- hidden compatibility DOM sentinels such as `studioCloneModelSelect`;
- the abandoned Tauri `apps/desktop` shell;
- Tauri IPC in `apps/client`.

Architecture tests assert that the retired desktop-companion and Tauri surfaces remain absent.

## `runtime` — inference and local service ownership

The Python runtime owns:

- inference orchestration;
- modular and direct translation strategy selection;
- model registry/catalog state;
- model install/activation/uninstall ownership;
- backend-owned installability reasons;
- voice-profile persistence/normalization/synthesis;
- GPU/model process supervision;
- TTS manifests/runtime profiles/backend runtime catalog;
- local HTTP/bootstrap/session APIs;
- caption/event transport;
- native-audio routing/configuration orchestration.

The client consumes stable contracts rather than reproducing implementation details.

## Native audio ownership

### `crates/audio-core`

Portable native audio types/contracts:

- endpoint roles;
- stream configuration;
- bounded capture/render abstractions;
- protocol-neutral audio platform interfaces.

### `crates/audio-windows`

Windows Core Audio implementation:

- MMDevice stable endpoint enumeration;
- WASAPI microphone capture;
- WASAPI render loopback capture;
- bounded WASAPI render output;
- Windows native helper executable.

### `crates/audio-linux`

Linux implementation:

- PipeWire/PipeWire-Pulse endpoint discovery;
- physical capture;
- sink-monitor loopback/system capture;
- render output;
- Linux native helper executable.

### `native/macos/audio-helper`

macOS CoreAudio implementation:

- stable CoreAudio UID enumeration;
- physical microphone/output I/O;
- macOS 14.2+ Core Audio process taps for system capture;
- direct device I/O for VoxPassport HAL endpoints;
- PCM normalization at the native boundary.

### `drivers/*/virtual-audio`

Platform system-facing virtual microphone implementations and their install/build/validation tooling.

The virtual endpoint names are consistent across desktop OSes:

- `VoxPassport Translation Sink`;
- `VoxPassport Virtual Microphone`.

## `account_api` — optional account service

The account service is independent of the local inference daemon. It owns PostgreSQL-backed users/sessions/provider credentials when accounts are enabled.

Local-only deployments disable this boundary and do not require PostgreSQL or a VoxPassport account.

## TTS ownership

```text
runtime/tts_manifests/
    model identity/capabilities/driver metadata

runtime/tts_backend_runtimes/
    reusable backend server-family lifecycle metadata

runtime/profiles/
    dependency-compatible runtime environments

runtime/workers/tts_host/
    generic worker host and TtsDriver implementations

runtime/inference/tts_plugins/
    application adapter/supervisor/catalog integration
```

A model manifest does not own fixed worker/backend ports or application process topology.

## Where a change belongs

```text
Translator/Settings/Models/Voice UI
    -> apps/client

Expo platform behavior
    -> apps/client narrowly scoped platform module

Local runtime/session/bootstrap API
    -> runtime

Model installability/active-slot semantics
    -> runtime model registry/model-manager API

Windows capture/loopback/render/helper
    -> crates/audio-windows

Linux capture/loopback/render/helper
    -> crates/audio-linux

Portable audio contract
    -> crates/audio-core

macOS CoreAudio helper behavior
    -> native/macos/audio-helper

System virtual microphone implementation
    -> drivers/<platform>/virtual-audio

Inference/model/provider behavior
    -> runtime/inference

TTS model metadata
    -> runtime/tts_manifests

Reusable TTS backend server family
    -> runtime/tts_backend_runtimes

Browser-only meeting overlay/integration
    -> apps/browser-extension

Account/auth behavior
    -> account_api

Developer migration/admin/validation command
    -> scripts
```

## Naming rules

- Name modules after enduring responsibility, not why they were added.
- Do not create `*-fixes.*`, `*-patch.*`, `new-*`, `old-*`, or numbered replacement modules in canonical code.
- Do not create `apps/desktop`, `apps/desktop-companion`, or another duplicate product UI without first changing the architecture plan explicitly.
- Do not put model/provider process topology in Expo components.
- Do not route raw PCM through React state or REST JSON.

## Architectural invariants

1. One canonical product UI: `apps/client`.
2. Desktop priority does not create a second UI framework.
3. Platform-native audio stays behind stable runtime/native contracts.
4. High-frequency PCM remains on native/subprocess media paths.
5. Communication platform and inference provider are independent axes.
6. Providers/models are selected through capability/contracts rather than UI model-name branches.
7. Local/self-hosted operation never depends on VoxPassport-hosted infrastructure.
8. Voice profiles remain model-independent.
9. TTS process topology/residency belongs to the supervisor.
10. Legacy patch layers and retired desktop surfaces stay removed.
11. Hosted CI validation and physical-device acceptance are documented separately.
