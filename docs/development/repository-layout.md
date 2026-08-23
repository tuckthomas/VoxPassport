# Repository Layout and Ownership

This document is the routing map for human and AI developers. Put behavior in the directory that owns the behavior; do not encode implementation history in filenames or add patch layers around the owning module.

## Canonical top-level ownership

```text
VoxPassport/
├── apps/
│   ├── client/              Canonical Expo + React Native + React Native Web UI
│   ├── browser-extension/   Browser-specific integration only
│   └── desktop-companion/   LEGACY migration source; not architectural target
├── runtime/                 Python inference/runtime and local service
├── crates/                  Native/shared Rust audio and protocol components
├── configs/                 User/operator configuration examples
├── native/                  OS integration/driver artifacts when needed
├── tests/                   Python/integration/architecture tests
├── benchmarks/              Reproducible model/runtime benchmarks
├── scripts/                 Developer/admin utilities; not production modules
├── docs/                    Architecture, operations, and development documentation
└── .agents/plans/           pending / in-progress / completed implementation plans
```

There is deliberately **no canonical `apps/desktop` product shell**. The product UI remains `apps/client` under Expo. Desktop system integration is provided behind local-runtime/native service contracts rather than by embedding the Expo UI in a second application framework.

## `apps/client` — canonical universal product UI

`apps/client` owns screens, presentation state, typed API clients, client-side settings, Expo audio/media integration where supported, and session/control UI for Android, iOS, and web/PWA.

It must not own:

- Python/model process lifecycle implementation;
- CUDA/model-library details;
- Windows WASAPI/CoreAudio/PipeWire implementation;
- system virtual-microphone drivers;
- high-frequency PCM processing that belongs in native/runtime code;
- model-name-specific process routing;
- hard-coded provider topology;
- iframe/eval/fetch monkey-patching;
- Tauri-specific IPC or dependencies.

Platform-specific Expo/React Native files (`*.native.ts`, `*.web.ts`, and narrowly scoped platform modules) are acceptable when the platform genuinely requires different behavior.

## Desktop use of the Expo client

Desktop is an immediate use case, but it does not get a second UI architecture. `apps/client` remains the product frontend.

Desktop-native capabilities such as:

- physical microphone capture;
- Windows WASAPI loopback capture;
- audio endpoint enumeration;
- translated-audio routing;
- a real system virtual-microphone endpoint;
- process/driver lifecycle;

belong behind stable local-runtime/native contracts. The Expo client consumes status/configuration/session APIs and does not carry raw realtime PCM through a UI-specific bridge.

An installable web/PWA experience can be produced from the Expo web target. Any future alternative desktop packaging mechanism must be an explicit architecture decision; do not introduce Tauri or another shell implicitly.

## `apps/browser-extension` — optional browser integration

The browser extension is for browser-specific overlays and integration. It is not the core desktop audio transport. Core desktop translation should be communication-platform independent wherever native/system audio routing permits it.

## `apps/desktop-companion` — legacy only

This directory contains the current prototype HTML UI and remains temporarily as migration source material. New features must not target it unless required to keep the existing product usable during migration.

Files such as `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` are technical debt, not a reusable extension mechanism.

For each legacy patch behavior:

1. identify the actual owner and original defect/obsolete assumption;
2. fix or replace the owning implementation;
3. preserve only enduring domain behavior in a proper abstraction;
4. delete the patch when its required behavior is covered;
5. do not copy the patch into the Expo client under a cleaner filename.

## `runtime` — Python inference and local service

The Python runtime owns model/inference behavior, the local HTTP/session API, GPU/model process supervision, registry/manifests, voice-profile processing, provider/runtime adapters, and coordination with native desktop audio services where applicable.

The UI consumes stable capability/API contracts rather than importing or reproducing Python implementation details.

Direct speech-to-speech providers and the modular `VAD -> ASR -> NMT -> TTS` pipeline are translation strategies behind runtime/session contracts, not communication-platform-specific implementations.

## `crates` — native/shared Rust

Rust crates own reusable native audio/protocol code that is independent of the Expo UI framework.

Current direction:

```text
crates/
├── protocol/        Shared Rust wire/audio types
├── audio-core/      Portable audio buses, buffers, endpoint/platform contracts
└── audio-windows/   Windows Core Audio/WASAPI implementation
```

Future macOS/Linux implementations should satisfy the same portable contracts rather than require product-screen changes.

These crates may be used by a local native audio service/helper or other explicitly approved integration boundary. Their existence does not imply a Tauri desktop application.

## Where a change belongs

```text
Change Translator/Settings/Models UI
    -> apps/client

Change Expo client platform behavior
    -> apps/client platform-specific module

Change local runtime/session API
    -> runtime

Change Windows audio device/capture/loopback behavior
    -> crates/audio-windows

Change portable audio abstractions
    -> crates/audio-core

Change system virtual-microphone driver/helper
    -> native and/or native audio service code

Change inference/model/provider behavior
    -> runtime/inference

Add/modify TTS model metadata
    -> runtime/tts_manifests

Add reusable TTS backend server family
    -> runtime/tts_backend_runtimes

Change browser-only meeting integration
    -> apps/browser-extension

Add developer one-off migration/admin command
    -> scripts
```

## Naming rules

- Name modules after their enduring responsibility, not why they were added.
- Do not create `*-fixes.*`, `*-patch.*`, `new-*`, `old-*`, or numbered replacement files in canonical application code.
- A temporary compatibility module must live under an explicitly named `legacy`/`compat` boundary, explain its removal condition, and have a tracked migration plan.
- Do not create `apps/desktop` or add Tauri dependencies unless the architecture is explicitly changed in the plan first.
- Do not use `model-manager` for an application surface that owns unrelated product workflows.

## Architectural invariants

1. One canonical product UI: `apps/client` using Expo + React Native + React Native Web.
2. Desktop priority does not create a second UI framework.
3. Desktop-native audio/driver work stays behind runtime/native contracts.
4. Communication platform and inference provider are independent axes.
5. Providers/models are selected by capabilities/contracts rather than UI model-name branches.
6. Local/self-hosted operation does not depend on VoxPassport Cloud.
7. Mobile implementation can be deferred without compromising the universal Expo client architecture.
8. Legacy patch files are removed by correcting their causes, not consolidated wholesale.
9. Tauri is not part of the current architecture.
