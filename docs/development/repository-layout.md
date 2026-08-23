# Repository Layout and Ownership

This document is the routing map for human and AI developers. Put behavior in the directory that owns the behavior; do not encode implementation history in filenames or add patch layers around the owning module.

## Canonical top-level ownership

```text
VoxPassport/
├── apps/
│   ├── client/              Shared Expo + React Native + React Native Web UI
│   ├── desktop/             Thin Tauri desktop shell; no duplicate product UI
│   ├── browser-extension/   Browser-specific integration only
│   └── desktop-companion/   LEGACY migration source; not architectural target
├── runtime/                 Python inference/runtime implementation
├── crates/                  Native/shared Rust audio and protocol components
├── configs/                 User/operator configuration examples
├── native/                  Native artifacts outside the Rust workspace when needed
├── tests/                   Python/integration/architecture tests
├── benchmarks/              Reproducible model/runtime benchmarks
├── scripts/                 Developer/admin utilities; not production modules
├── docs/                    Architecture, operations, and development documentation
└── .agents/plans/           pending / in-progress / completed implementation plans
```

## `apps/client` — shared product UI

`apps/client` is the canonical frontend. It owns screens, presentation state, typed API clients, client-side settings, and low-frequency UI events.

It must not own:

- Python/model process lifecycle implementation;
- CUDA/model-library details;
- realtime PCM processing;
- Windows WASAPI/CoreAudio/PipeWire implementation;
- model-name-specific process routing;
- hard-coded provider topology;
- iframe/eval/fetch monkey-patching.

Platform-specific files (`*.native.ts`, `*.web.ts`) are acceptable only when the platform genuinely requires different behavior.

## `apps/desktop` — installable desktop shell

`apps/desktop` packages the exported `apps/client` web build in Tauri. It owns desktop application lifecycle and the narrow IPC boundary to native capabilities.

The desktop shell may expose typed commands such as:

- local runtime status/start/stop;
- audio endpoint enumeration;
- selected audio route state;
- system integration state.

It must not duplicate Translator, Models, Voice Profiles, Settings, or other product screens. Realtime PCM must stay in native/runtime code rather than crossing the React/Tauri command boundary.

## `apps/browser-extension` — optional browser integration

The browser extension is for browser-specific integration and overlays. It is not the primary desktop audio transport. Core desktop translation should work through native audio routing/virtual endpoints without requiring a Zoom/Meet-specific extension.

## `apps/desktop-companion` — legacy only

This directory contains the current prototype HTML UI and remains temporarily as migration source material. New features must not target it unless required to keep the existing product usable during migration.

Files such as `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` are technical debt, not a reusable extension mechanism.

For each legacy patch behavior:

1. identify the actual owner and original defect/obsolete assumption;
2. fix or replace the owning implementation;
3. preserve only enduring domain behavior in a proper abstraction;
4. delete the patch when its required behavior is covered;
5. do not copy the patch into the new client under a cleaner filename.

## `runtime` — Python inference and local service

The Python runtime owns model/inference behavior, the local HTTP/session API, GPU/model process supervision, registry/manifests, voice-profile processing, and provider/runtime adapters.

The UI should consume stable capability/API contracts rather than import or reproduce Python implementation details.

Direct speech-to-speech providers and the modular `VAD -> ASR -> NMT -> TTS` pipeline are translation strategies behind runtime/session contracts, not communication-platform-specific implementations.

## `crates` — native/shared Rust

Rust crates own portable native contracts and OS-specific native implementations.

Current direction:

```text
crates/
├── protocol/        Shared Rust wire/audio types
├── audio-core/      Portable audio buses, buffers, endpoint/platform contracts
└── audio-windows/   Windows Core Audio/WASAPI implementation
```

Future macOS/Linux implementations should satisfy the same `audio-core` platform contracts rather than require client-screen changes.

## Where a change belongs

```text
Change Translator/Settings/Models UI
    -> apps/client

Change desktop window/process/native command bridge
    -> apps/desktop

Change Windows audio device/capture/loopback behavior
    -> crates/audio-windows

Change portable audio abstractions
    -> crates/audio-core

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
- Do not use `desktop` to describe a browser page. `apps/desktop` means the installable native shell.
- Do not use `model-manager` for an application surface that owns unrelated product workflows.

## Architectural invariants

1. One canonical shared UI: `apps/client`.
2. Desktop is an installable shell plus native capabilities, not a second UI.
3. Audio realtime path stays native/runtime-side.
4. Communication platform and inference provider are independent axes.
5. Providers/models are selected by capabilities/contracts rather than UI model-name branches.
6. Local/self-hosted operation does not depend on VoxPassport Cloud.
7. Mobile is deferred; shared client contracts must remain mobile-compatible.
8. Legacy patch files are removed by correcting their causes, not consolidated wholesale.
