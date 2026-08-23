# Universal Expo Client + VoxPassport Platform Architecture Plan

Status: In progress — Expo migration underway; desktop workflow is the immediate implementation priority. Tauri is not part of the architecture.

Purpose: Replace the prototype browser-only frontend with one maintainable Expo + React Native + React Native Web client, preserve local/self-hosted inference, add provider-agnostic direct speech translation, and support desktop system-audio integration through the local runtime/native audio layer rather than a second desktop UI framework. Android/iOS remain first-class future targets of the same Expo client. VoxPassport Cloud remains optional managed infrastructure, not a prerequisite for local/personal use.

## Product architecture decision

- [x] Use Expo + React Native + React Native Web as the canonical product client architecture.
- [x] Use Expo Router for universal file-based navigation.
- [x] Target Expo SDK 57 / React Native 0.86 / React 19.2.x as the current implementation baseline.
- [x] Keep the browser extension separate because it is genuinely browser-specific integration code.
- [x] Keep `apps/client` as the one product UI for Android, iOS, web/PWA, and desktop-oriented web/PWA workflows.
- [x] Do **not** use Tauri or create a second desktop UI shell.
- [x] Keep desktop as the immediate workflow priority without changing the canonical Expo architecture.
- [x] Put Windows system audio, virtual-microphone, loopback, and driver work behind runtime/native contracts rather than UI-framework IPC.
- [x] Keep local/self-hosted use available without VoxPassport-hosted infrastructure.
- [x] Defer mobile call-transport implementation while preserving mobile-compatible client contracts.
- [x] Prefer a future VoxPassport-native calling/WebRTC path on mobile instead of assuming arbitrary cross-app microphone injection.

## Desktop use of Expo

- [x] Treat the Expo web/PWA target as the desktop-facing product UI during this phase.
- [x] Keep communication-platform integration independent from inference-provider selection.
- [x] Keep Zoom/Meet/Teams/etc. plugins/extensions optional for richer UX rather than required core transport.
- [x] Preserve reusable Rust audio crates independently of any desktop shell framework.
- [ ] Expose native desktop audio capabilities to the Expo client through stable local-runtime APIs/services.
- [ ] Implement Windows microphone capture in the native audio layer.
- [ ] Implement Windows WASAPI loopback capture in the native audio layer.
- [ ] Implement/select a real Windows virtual-microphone endpoint/driver path.
- [ ] Add device/routing selection endpoints to the local runtime.
- [ ] Add echo/feedback ownership so translated output is never re-ingested as source audio.
- [ ] Validate desktop PWA/install workflow and native audio helper/service startup together on Windows.
- [ ] Do not mark desktop system-wide translation complete until Zoom/Meet/Teams can select/use the actual translated microphone endpoint.

## Provider/model architecture

- [x] Keep the existing modular `VAD -> ASR -> NMT -> TTS` pipeline.
- [x] Define `DIRECT_SPEECH_TRANSLATION` as a separate first-class capability.
- [x] Add provider/strategy metadata independently from communication transport.
- [x] Add a provider-agnostic direct-speech translation catalog.
- [x] Register Gemini 3.5 Live Translate declaratively as a BYO-API direct-speech strategy.
- [x] Keep Google/Gemini-specific metadata out of generic Expo UI components.
- [x] Distinguish execution modes such as local, BYO API, self-hosted/private, and managed cloud.
- [ ] Define the executable streaming session interface shared by modular and direct-speech strategies.
- [ ] Add a Gemini Live Translate provider/session implementation behind that interface.
- [ ] Add provider authentication/secret handling that does not serialize API keys into ordinary UI state/logs.
- [ ] Add provider capability display for languages, voice preservation, streaming, lifecycle/preview state, and billing ownership.

## Repository organization

- [x] Make `apps/client/` the canonical universal product frontend.
- [x] Keep `apps/browser-extension/` for browser-specific integration only.
- [x] Keep `apps/desktop-companion/` explicitly legacy during migration.
- [x] Remove the unintended `apps/desktop/` Tauri shell.
- [x] Remove Tauri dependencies and IPC bridge code from `apps/client`.
- [x] Add `docs/development/repository-layout.md` with ownership/routing rules.
- [x] Add architecture tests that fail if a Tauri desktop shell/dependency is reintroduced without an architecture change.
- [x] Keep native audio code in `crates/audio-core` / `crates/audio-windows`, independent of Expo UI framework choices.
- [x] Remove the stale nonexistent Rust `ipc-client` workspace member rather than preserving a dead topology entry.
- [ ] Move/rename the legacy HTML frontend only after the Expo client reaches sufficient parity.

## Expo client foundation

- [x] Scaffold `apps/client` as a TypeScript Expo project.
- [x] Configure Expo Router and React Native Web.
- [x] Add strict TypeScript configuration.
- [x] Add `expo-audio` and microphone permission configuration without enabling background recording by default.
- [x] Add cross-platform settings storage.
- [x] Add reusable design tokens, screen layout, and card primitives.
- [x] Create thin Expo routes backed by feature-oriented `src/features/...` modules.
- [x] Add Translator, Models & Engines, Voice Profiles, Runtime/Diagnostics, and Settings routes.
- [x] Add a typed text-translation workflow against the selected runtime target.
- [x] Add typed model and voice-profile rendering from backend APIs rather than legacy global-array mutation.
- [x] Keep feature modules independent from provider/model process topology.
- [ ] Implement the production live-audio Translator workflow.
- [ ] Add voice enrollment/preview/activation workflows using typed API services.
- [ ] Add model activation/install/uninstall workflows using typed services and backend-owned metadata.
- [ ] Add live captions/session state UI using the versioned session protocol.

## Client runtime abstraction

- [x] Define typed runtime/session contracts.
- [x] Define a `RuntimeTarget` abstraction with local, self-hosted, and future cloud modes.
- [x] Centralize active runtime URL selection in `RuntimeTargetContext`.
- [x] Centralize HTTP access in `VoxPassportApi`.
- [x] Centralize feature access through `useVoxPassportApi()` without Tauri/native-shell transport branches.
- [x] Support configurable local and self-hosted runtime URLs.
- [x] Keep feature screens independent from localhost, AWS, GPU process, worker-port, or UI-shell assumptions.
- [ ] Centralize live media/session transport behind a session service.
- [ ] Add authenticated self-hosted/cloud session handling without leaking credentials.

## Local runtime compatibility

- [x] Preserve the Python runtime as owner of models, GPU processes, inference supervision, TTS runtime management, and local session orchestration.
- [x] Preserve existing local REST APIs during migration.
- [x] Do not make Expo components start/manage individual Python/CUDA workers.
- [ ] Add a versioned `/api/client/bootstrap` endpoint exposing runtime/session capability URLs generically.
- [ ] Add explicit CORS handling for approved Expo web/PWA localhost development origins.
- [ ] Add native-audio capability/status endpoints for desktop use.
- [ ] Add audio device/routing configuration endpoints using stable OS endpoint IDs rather than sounddevice indices in the client contract.
- [ ] Add a runtime-owned native audio service/helper lifecycle if direct Python audio ownership cannot provide the required Windows routing cleanly.

## Desktop native audio architecture

- [x] Existing shared protocol distinguishes physical mic, remote conference, outbound translated TTS, inbound translated TTS, virtual mic, and local monitor buses.
- [x] Audit the Python pipeline: `AudioCaptureEngine`/`AudioPlaybackEngine` currently use `sounddevice`; `AudioBus.VIRTUAL_MIC` is only a logical bus and does not create an OS virtual microphone.
- [x] Define portable native audio endpoint/platform contracts in `audio-core`.
- [x] Implement Windows Core Audio endpoint enumeration code with stable MMDevice IDs, friendly names, and default-device detection in `audio-windows`.
- [x] Keep those native contracts reusable without tying them to Tauri.
- [ ] Compile/execute Windows endpoint enumeration against real hardware.
- [ ] Define the native-audio-to-Python/session transport explicitly.
- [ ] Implement physical microphone WASAPI capture.
- [ ] Implement WASAPI loopback capture.
- [ ] Define translated-output sink abstraction.
- [ ] Implement or integrate a real Windows virtual microphone endpoint.
- [ ] Route native audio status/control through the local runtime for consumption by the Expo UI.
- [ ] Keep raw high-frequency PCM out of React component state and ordinary REST/UI event paths.

## Mobile deferred phase

- [x] Preserve Android/iOS as targets of `apps/client` rather than introducing separate client frameworks.
- [x] Defer mobile calling implementation while desktop workflow is established.
- [x] Prefer a future VoxPassport-native/WebRTC call transport on mobile.
- [ ] Revisit iOS microphone injection only if Apple permits the intended translation use case.
- [ ] Revisit Android cross-app injection only if Google exposes a sanctioned public capability.

## Fix-layer cleanup rule

For every legacy `*-fixes.js` behavior:

- [ ] If it compensates for broken/obsolete original behavior: correct the owner implementation and delete the patch.
- [ ] If it exists only for compatibility with a removed design: delete it entirely.
- [ ] If it implements enduring domain behavior: reimplement it in the proper Expo/client/backend abstraction, not by copying the patch.
- [ ] If it hard-codes metadata now available from APIs/manifests: make the Expo UI data-driven and delete the hard-coded logic.
- [ ] If it is temporary migration logic: finish the migration and delete it.
- [x] Do not create new `*-fixes.js`, iframe `eval()` bridges, hidden compatibility elements, fetch monkey-patches, Tauri bridges, or duplicate desktop screens.

## Legacy patch-specific migration

- [x] New model catalog rendering uses typed backend data rather than legacy global arrays.
- [x] New voice-profile rendering uses backend state rather than legacy DOM/global state.
- [x] New text translation constructs the correct request at its typed API source instead of relying on fetch interception.
- [ ] Replace remaining voice enrollment/synthesis request interception as those workflows migrate.
- [ ] Eliminate the hidden `studioCloneModelSelect` compatibility sentinel rather than recreating it.
- [ ] Retire Silero v4-to-v6 UI repair once canonical backend metadata fully covers it.
- [ ] Replace `stack-upgrade-fixes.js` hard-coded install exceptions with generic backend installation-state/reason metadata.
- [ ] Delete each legacy fix file only after its required behavior is covered by the new owner implementation or explicitly retired.

## VoxPassport Cloud — optional/later

- [x] Keep hosted cloud optional rather than required for personal/local use.
- [x] Preserve the control-plane/media-plane design: control plane allocates/authenticates; latency-sensitive media can stream directly to allocated workers/providers when safe.
- [ ] Create `services/cloud-control-plane` only when hosted service implementation resumes.
- [ ] Add allocation, short-lived credentials, usage accounting, and pricing policy as server-side concerns.
- [ ] Do not block desktop/local Expo migration on cloud infrastructure.

## Tests and validation

- [x] Add static architecture tests preventing new patch-history files in `apps/client`.
- [x] Add architecture tests preventing Tauri dependencies/references and `apps/desktop` reintroduction.
- [x] Add direct translation provider-catalog tests.
- [x] Add Expo TypeScript typecheck and web export commands.
- [x] Add CI job for Expo typecheck/web export.
- [x] Keep Windows Rust checks for reusable audio crates, independent of any desktop shell.
- [ ] Observe CI results and fix failures.
- [ ] Add local runtime bootstrap/CORS contract tests.
- [ ] Add session protocol tests/examples.
- [ ] Validate Expo web build/PWA in a browser.
- [ ] Validate Android development build later.
- [ ] Validate iOS development build later.
- [ ] Validate Windows endpoint enumeration/capture/loopback on real hardware.
- [ ] Validate an actual system virtual microphone with a conferencing application.
- [x] Keep this plan in `in-progress` while platform/hardware validation remains outstanding.

## Current desktop acceptance path

```text
Expo / React Native Web client
        |
        | typed control/session APIs
        v
VoxPassport Local Runtime
        |
        +--> local modular inference
        +--> direct speech provider adapters
        +--> native desktop audio service/contracts
                    |
                    +--> physical microphone capture
                    +--> conference/system loopback capture
                    +--> translated local monitor
                    +--> real virtual microphone output
```

The UI remains Expo. Native Windows audio is an implementation service behind the runtime boundary, not a second application shell.

## Migration completion criteria

- [ ] The Expo client covers the production workflows currently expected from the legacy Studio.
- [ ] Desktop live translation works through runtime/native audio contracts without Tauri.
- [ ] A real Windows virtual microphone path is validated with at least one conferencing application.
- [ ] The local runtime no longer needs to serve `apps/desktop-companion/model-manager` as the primary UI.
- [ ] `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` are deleted because their causes were corrected/replaced.
- [ ] The misleading `desktop-companion` directory is removed or archived under an explicitly legacy path.
- [ ] Documentation and commands consistently describe the Expo architecture.
- [ ] Move this plan to `.agents/plans/completed/` only after functional parity and required platform validation are complete.
