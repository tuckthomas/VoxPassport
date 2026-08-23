# Desktop-First Universal Client + Platform Architecture Plan

Status: In progress

Purpose: Replace the prototype browser-only frontend architecture with a maintainable shared client while prioritizing the installable desktop product. Desktop must own system-audio integration, local-runtime lifecycle, virtual microphone/loopback routing, and provider-agnostic translation. Android/iOS remain future targets using the same Expo/React Native client foundation, with a VoxPassport-native calling application as the preferred mobile path rather than attempting unsupported cross-app virtual-microphone injection. VoxPassport Cloud is optional/later; local/self-hosted operation remains a first-class product mode.

## Product architecture decision

- [x] Use Expo + React Native + React Native Web as the shared client architecture.
- [x] Use Expo Router for universal file-based navigation.
- [x] Keep the browser extension separate because it is genuinely browser-specific integration code.
- [x] Make desktop the immediate product target.
- [x] Package the shared web export in a thin Tauri 2 desktop shell for Windows first, with macOS/Linux as later packaging targets.
- [x] Keep native/system functions outside the React UI: audio devices, virtual microphone/loopback, runtime lifecycle, process cleanup, and OS integration belong to Rust/native/backend code.
- [x] Keep web/PWA usable against the local VoxPassport runtime for development and users who explicitly prefer browser access.
- [x] Defer mobile calling implementation; document VoxPassport-to-VoxPassport calling as the preferred future Android/iOS transport.
- [x] Do not assume Android will gain a general public virtual-microphone API.
- [x] Treat VoxPassport Cloud as optional managed infrastructure rather than a prerequisite for the local/personal edition.

## Commercial/product boundary

- [x] Preserve a local/self-hosted path that does not require VoxPassport-hosted inference.
- [x] Keep provider selection open: local modular ASR/NMT/TTS, direct speech-translation providers such as Gemini Live Translate, private workers, and future providers can coexist behind capability contracts.
- [ ] Add `DIRECT_SPEECH_TRANSLATION` as a first-class inference strategy/capability rather than pretending direct audio-to-audio providers are ordinary ASR/NMT/TTS checkpoints.
- [ ] Add provider metadata that distinguishes local, BYO-key cloud, managed cloud, and private/self-hosted execution.
- [ ] Keep licensing/product-tier concerns outside inference implementation; do not hard-code commercial policy into model drivers.

## Repository organization

- [x] Make `apps/client/` the canonical shared product frontend.
- [ ] Create `apps/desktop/` as the Tauri shell only; it must consume `apps/client` output rather than duplicate UI code.
- [ ] Remove the misleading `apps/desktop-companion` naming from the long-term architecture.
- [x] Keep `apps/browser-extension/` for the browser extension only.
- [ ] Move the legacy HTML frontend under a clearly labeled legacy/migration location until functional parity is reached.
- [ ] Document ownership boundaries so humans and AI agents can infer where client, desktop shell, local runtime, inference providers, protocols, workers, and browser integration live.
- [x] Delete superseded pending frontend/mobile plans once their still-relevant requirements are incorporated here.

## Shared client foundation

- [x] Scaffold `apps/client` as a TypeScript Expo project.
- [x] Configure Expo Router/React Native Web dependencies and TypeScript.
- [x] Add `expo-audio` and native microphone permission configuration without enabling background recording by default.
- [x] Create shared visual primitives/theme rather than another monolithic HTML page.
- [ ] Create feature-oriented routes/screens for Translator, Models/Engines, Voice Profiles, Runtime/Diagnostics, and Settings.
- [ ] Keep platform-specific implementation files narrowly scoped (`*.native.ts`, `*.web.ts`) only where behavior genuinely differs.

## Desktop shell

- [ ] Scaffold `apps/desktop` with Tauri 2 and configure it to package the exported `apps/client` web bundle.
- [ ] Add Tauri commands for local-runtime status/start/stop without putting process logic in React components.
- [ ] Ensure runtime process ownership is explicit and cleanup occurs when VoxPassport-owned runtime processes exit/restart.
- [ ] Add a native capability bridge for audio-device enumeration/status.
- [ ] Reuse/extend `crates/audio-core` and platform crates rather than implementing audio logic in the Tauri UI shell.
- [ ] Treat Windows WASAPI as the first executable desktop audio target.
- [ ] Define portable audio traits/contracts so CoreAudio/PipeWire implementations can be added without changing client code.
- [ ] Add explicit desktop capability reporting: physical microphone, loopback capture, virtual-mic output, runtime process control, and supported platform features.
- [ ] Do not claim virtual-microphone support is complete until an actual selectable system endpoint/driver path is validated on the development machine.

## Client runtime abstraction

- [x] Define typed runtime/session contracts.
- [ ] Define a client-side `RuntimeTarget` abstraction with at least `local` and future `cloud`/`self_hosted` modes.
- [ ] Keep screens/components independent from localhost, AWS, model process, and worker-port assumptions.
- [ ] Centralize HTTP/API access in one typed API client.
- [ ] Centralize live session/media transport behind a session service.
- [ ] Support local runtime URL configuration.
- [ ] Keep access/session tokens out of ordinary logs and UI state serialization.

## Local runtime compatibility

- [ ] Add a versioned `/api/client/bootstrap` endpoint so the shared client can discover capabilities and endpoints generically.
- [ ] Add explicit CORS handling for approved localhost development/web origins instead of relying on same-origin legacy HTML.
- [ ] Preserve existing local APIs during migration.
- [x] Preserve the local runtime as the owner of models, GPU processes, inference supervision, and TTS runtime management.
- [ ] Move desktop system-audio ownership toward the native audio layer rather than browser media APIs.
- [ ] Do not make the client responsible for starting Python/CUDA workers directly.

## Translation-engine abstraction

- [ ] Define translation strategies independently from communication transport.
- [ ] Keep the existing modular pipeline (`VAD -> ASR -> NMT -> TTS`) as one strategy.
- [ ] Add direct speech-to-speech strategy metadata suitable for Gemini Live Translate and future equivalents.
- [ ] Do not hard-code Google/Gemini assumptions into generic session or UI components.
- [ ] Show execution/provider information to users: local, provider API, private endpoint, or managed service.
- [ ] Allow a future provider adapter to expose languages, voice-preservation capability, streaming support, cost/usage metadata, and authentication requirements.

## Desktop audio architecture

- [ ] Define three separate buses: physical microphone input, remote/system loopback input, and translated virtual-microphone output.
- [ ] Keep raw high-frequency audio off Tauri/React IPC; native/runtime code owns realtime buffers and sends only UI-safe state/levels/events to the client.
- [ ] Add device enumeration and stable device identifiers to the audio platform contract.
- [ ] Add loopback capture selection for communication-app output.
- [ ] Add translated-output sink abstraction for a virtual microphone/system endpoint.
- [ ] Add echo/feedback ownership rules so synthesized translated output is not re-captured as source speech.
- [ ] Keep optional Zoom/Meet/etc. overlays/extensions as UX enhancements, not required audio transport.

## Mobile deferred phase

- [x] Defer Android/iOS implementation while desktop architecture is established.
- [x] Prefer a future VoxPassport-native calling app/WebRTC path on mobile instead of unsupported cross-app microphone injection.
- [ ] Preserve mobile-compatible contracts in `apps/client`; do not add desktop-only assumptions to shared screens/services.
- [ ] Revisit iOS microphone injection only if Apple permits the use case through public/approved APIs.
- [ ] Revisit Android cross-app injection only if Google exposes a sanctioned public API.

## Fix-layer cleanup rule

For every legacy `*-fixes.js` behavior, classify it before touching it:

- [ ] If it compensates for broken/obsolete original behavior: correct the owner implementation and delete the patch.
- [ ] If it exists only for compatibility with a removed design: delete it entirely.
- [ ] If it implements enduring domain behavior: reimplement that behavior in the proper client/backend abstraction, not by copying the patch.
- [ ] If it hard-codes metadata now available from APIs/manifests: make the UI data-driven and delete the hard-coded logic.
- [ ] If it is temporary migration logic: finish the migration and delete it.
- [x] Do not create new `*-fixes.js`, iframe `eval()` bridges, hidden compatibility elements, or fetch monkey-patches.

## Legacy patch-specific migration

- [ ] Replace `runtime-fixes.js` model-state synchronization with typed API/store state.
- [ ] Replace `runtime-fixes.js` request interception by constructing correct API requests at their source.
- [ ] Eliminate the hidden `studioCloneModelSelect` compatibility sentinel rather than recreating it.
- [ ] Replace `engine-catalog-fixes.js` global-array mutation with backend-driven model catalog rendering.
- [ ] Replace Silero v4-to-v6 UI repair with canonical backend metadata only.
- [ ] Replace `stack-upgrade-fixes.js` hard-coded install exceptions with generic backend-provided installation state/reason metadata.
- [ ] Delete each legacy fix file only after its required behavior is covered by the new owner implementation or explicitly retired.

## Frontend structure and maintainability

- [ ] No single generated/source UI file should become the replacement for the current ~288 KB `studio.html` monolith.
- [ ] Organize by feature/domain rather than patch chronology.
- [ ] Separate screens/routes, reusable components, API services, state, media transport, and platform integrations.
- [ ] Avoid model-name routing logic in UI components.
- [ ] Add a repository-layout document with explicit ownership rules for human and AI developers.

## Tests and validation

- [ ] Add static architecture tests that forbid new `*-fixes.js` files in the canonical client/desktop shell.
- [ ] Add local-runtime contract tests for bootstrap/CORS behavior.
- [ ] Add Rust tests/build checks for the desktop shell and audio capability contracts.
- [ ] Add TypeScript typecheck commands for `apps/client`.
- [ ] Add Expo project validation (`expo-doctor`) to documented local validation.
- [ ] Add client/desktop checks to CI when Node/Rust package installation is available.
- [ ] Run Python compile/tests available in the execution environment.
- [ ] Validate the Expo web export consumed by Tauri.
- [ ] Validate Tauri development build on Windows.
- [ ] Validate actual WASAPI loopback capture and physical microphone enumeration.
- [ ] Validate a real virtual-microphone endpoint/output path before marking system-wide conference integration complete.
- [ ] Keep plan in `in-progress` while hardware/platform validation remains outstanding.

## Immediate desktop acceptance path

```text
Physical microphone
        -> VoxPassport native audio/runtime
        -> selected translation strategy
        -> translated audio
        -> virtual microphone/system endpoint
        -> Zoom / Meet / Teams / Discord / softphone

Communication-app output
        -> WASAPI loopback
        -> VoxPassport translation strategy
        -> local speaker/headphones

Shared UI
        -> Expo/React Native Web
        -> Tauri desktop shell
        -> typed commands/state only; no realtime PCM over React IPC
```

## Completion criteria

- [ ] The shared client covers the production workflows currently expected from the legacy Studio.
- [ ] The desktop shell launches as an installable application and can discover/control the local runtime.
- [ ] Windows audio-device/loopback capability works through native code.
- [ ] The real virtual-microphone path is validated or explicitly separated as a remaining driver/install prerequisite.
- [ ] The local runtime no longer serves `apps/desktop-companion/model-manager` as the primary product UI.
- [ ] The legacy `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` are deleted because their causes were corrected/replaced.
- [ ] The misleading `desktop-companion` directory is removed.
- [ ] Documentation and commands reference the desktop-first shared-client architecture.
- [ ] Move this plan to `.agents/plans/completed/` only after desktop functional parity and required platform validation are complete.
