# Desktop-First Universal Client + Platform Architecture Plan

Status: In progress — architecture/scaffolding underway; executable Node/Rust/Windows validation still pending.

Purpose: Replace the prototype browser-only frontend architecture with a maintainable shared client while prioritizing the installable desktop product. Desktop owns system-audio integration, local-runtime lifecycle, virtual microphone/loopback routing, and provider-agnostic translation. Android/iOS remain future targets using the same Expo/React Native client foundation, with a VoxPassport-native calling application as the preferred mobile path rather than unsupported cross-app virtual-microphone injection. VoxPassport Cloud is optional/later; local/self-hosted operation remains first-class.

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
- [x] Define `DIRECT_SPEECH_TRANSLATION` as a first-class runtime capability in the shared Python protocol.
- [ ] Implement a direct-speech translation strategy/provider contract rather than treating audio-to-audio providers as ordinary ASR/NMT/TTS checkpoints.
- [ ] Add provider metadata that distinguishes local, BYO-key cloud, managed cloud, and private/self-hosted execution.
- [x] Keep licensing/product-tier concerns outside inference implementation; do not hard-code commercial policy into model drivers.

## Repository organization

- [x] Make `apps/client/` the canonical shared product frontend.
- [x] Create `apps/desktop/` as the Tauri shell only; it consumes `apps/client` output rather than duplicating UI code.
- [x] Keep `apps/browser-extension/` for browser-specific integration only.
- [x] Document `apps/desktop-companion/` as legacy migration source, not the long-term desktop architecture.
- [ ] Move/rename the legacy HTML frontend only when the local runtime no longer hard-codes its current path and the new client has sufficient parity.
- [x] Document ownership boundaries so humans and AI agents can infer where client, desktop shell, local runtime, inference providers, protocols, workers, and browser integration live.
- [x] Add `docs/development/repository-layout.md` with routing/naming rules.
- [x] Delete superseded pending frontend/mobile plans once their still-relevant requirements are incorporated here.

## Shared client foundation

- [x] Scaffold `apps/client` as a TypeScript Expo project.
- [x] Configure Expo Router/React Native Web dependencies and TypeScript.
- [x] Add `expo-audio` and native microphone permission configuration without enabling background recording by default.
- [x] Create shared visual primitives/theme rather than another monolithic HTML page.
- [x] Add routes/screens for Models/Engines, Voice Profiles, Runtime/Diagnostics, and Settings.
- [ ] Implement the production Translator workflow in the new client.
- [ ] Move substantial screen/domain logic under feature-oriented modules as it grows; keep Expo route files thin.
- [x] Keep platform-specific native integration behind a dedicated desktop bridge instead of scattering Tauri checks through screens.

## Desktop shell

- [x] Scaffold `apps/desktop` with Tauri 2 and configure it to package the exported `apps/client` web bundle.
- [x] Add Tauri commands for local-runtime status/start/stop without putting process logic in React components.
- [x] Track ownership of VoxPassport-started runtime processes and clean them up when the desktop manager is dropped/stopped.
- [x] Add a native capability bridge for audio status.
- [x] Add a native command for audio endpoint enumeration.
- [x] Reuse/extend `crates/audio-core` and platform crates rather than implementing audio logic in the Tauri UI shell.
- [x] Treat Windows WASAPI/Core Audio as the first executable desktop audio target.
- [x] Define portable audio platform/endpoint contracts so CoreAudio/PipeWire implementations can be added without changing client code.
- [x] Add explicit desktop capability reporting for enumeration, capture, loopback, virtual-mic output, and runtime process control.
- [x] Report unsupported/unimplemented audio functions conservatively rather than inferring support from a crate/module name.
- [ ] Package the Python/local runtime for installed desktop use; current runtime launch assumes a source/development checkout and `.venv` or `VOXPASSPORT_PYTHON`.
- [ ] Do not claim virtual-microphone support is complete until an actual selectable system endpoint/driver path is validated on the development machine.

## Client runtime abstraction

- [x] Define typed runtime/session contracts.
- [x] Define a client-side `RuntimeTarget` abstraction with `local`, `self_hosted`, and future `cloud` modes.
- [x] Centralize active runtime URL selection in `RuntimeTargetContext`.
- [x] Centralize HTTP/API access in one typed `VoxPassportApi` client.
- [x] Support configurable local and self-hosted runtime URLs.
- [x] Keep current screens independent from AWS/model-process/worker-port details.
- [ ] Centralize live session/media transport behind a session service.
- [ ] Add authenticated provider/self-hosted session handling without placing tokens in ordinary logs or serialized UI state.

## Local runtime compatibility

- [ ] Add a versioned `/api/client/bootstrap` endpoint so the shared client can discover capabilities and endpoints generically.
- [ ] Add explicit CORS handling for approved localhost/Tauri/web development origins instead of relying on same-origin legacy HTML.
- [x] Preserve existing local APIs during migration.
- [x] Preserve the local Python runtime as owner of models, GPU processes, inference supervision, and TTS runtime management.
- [x] Move desktop system-audio ownership toward native Rust audio contracts rather than browser media APIs.
- [x] Keep direct Python/CUDA worker management out of React components; the desktop shell only starts/stops the top-level local runtime it owns.

## Translation-engine abstraction

- [x] Keep `DIRECT_SPEECH_TRANSLATION` distinct from ASR, TRANSLATION, and TTS capability types.
- [ ] Define translation strategies independently from communication transport.
- [ ] Keep the existing modular pipeline (`VAD -> ASR -> NMT -> TTS`) as one explicit strategy.
- [ ] Add direct speech-to-speech strategy metadata suitable for Gemini Live Translate and future equivalents.
- [ ] Do not hard-code Google/Gemini assumptions into generic session or UI components.
- [ ] Show execution/provider information to users: local, BYO provider API, private endpoint, or managed service.
- [ ] Allow provider adapters to expose languages, voice-preservation capability, streaming support, cost/usage metadata, and authentication requirements.

## Desktop audio architecture

- [x] Existing protocol/audio buses distinguish physical microphone, remote conference audio, translated TTS, virtual microphone, and local monitor paths.
- [x] Keep raw high-frequency audio off Tauri/React IPC; native/runtime code owns realtime buffers and sends only UI-safe state/device metadata/events to the client.
- [x] Add portable device enumeration and stable OS endpoint identifiers to the audio platform contract.
- [x] Implement Windows Core Audio endpoint enumeration code for active capture/render devices, friendly names, and default endpoint detection.
- [x] Wire endpoint enumeration through Tauri to the shared Runtime & Audio screen.
- [ ] Compile/execute the Windows endpoint enumeration implementation against the pinned `windows` crate and real hardware.
- [ ] Implement physical microphone WASAPI capture.
- [ ] Implement WASAPI loopback capture for communication-app output.
- [ ] Add translated-output sink abstraction for a virtual microphone/system endpoint.
- [ ] Implement/install a real Windows virtual microphone endpoint or validated compatible driver path.
- [ ] Add echo/feedback ownership rules so synthesized translated output is not re-captured as source speech.
- [x] Keep optional Zoom/Meet/etc. overlays/extensions as UX enhancements, not required desktop audio transport.

## Mobile deferred phase

- [x] Defer Android/iOS implementation while desktop architecture is established.
- [x] Prefer a future VoxPassport-native calling app/WebRTC path on mobile instead of unsupported cross-app microphone injection.
- [x] Preserve mobile-compatible runtime target/API contracts in the shared client; desktop-only behavior is isolated behind the Tauri bridge.
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
- [x] Add architecture tests that reject new `*-fixes.*`/`*-patch.*` files and iframe/eval bridge patterns in canonical client/desktop code.

## Legacy patch-specific migration

- [x] New model catalog rendering reads backend model entries through the typed API instead of mutating legacy global arrays.
- [x] New voice-profile rendering reads backend profile state rather than legacy DOM/global state.
- [x] New desktop runtime/audio state uses typed Tauri/API state rather than `runtime-fixes.js` lexical `eval` synchronization.
- [ ] Replace all remaining `runtime-fixes.js` request interception by constructing correct requests at their source in new feature services.
- [ ] Eliminate the hidden `studioCloneModelSelect` compatibility sentinel rather than recreating it.
- [ ] Retire the Silero v4-to-v6 legacy UI repair after new client parity confirms canonical backend metadata is sufficient.
- [ ] Replace `stack-upgrade-fixes.js` hard-coded install exceptions with generic backend-provided installation state/reason metadata.
- [ ] Delete each legacy fix file only after its required behavior is covered by the new owner implementation or explicitly retired.

## Frontend structure and maintainability

- [x] No monolithic replacement for the current ~288 KB `studio.html`; new UI is split across routes, components, API/config/storage, and native bridge modules.
- [x] Separate reusable visual components, API services, runtime-target state, storage, and desktop/native integration.
- [x] Avoid model-name routing logic in new UI components.
- [x] Add repository-layout/naming rules for human and AI developers.
- [ ] Continue extracting feature-oriented modules as Translator/Voice enrollment/model actions are migrated.

## Tests and validation

- [x] Add static architecture tests that forbid new patch-history files in canonical client/desktop code.
- [x] Add a TypeScript `typecheck` command for `apps/client`.
- [x] Add an Expo `doctor` command for documented local validation.
- [ ] Add local-runtime contract tests for bootstrap/CORS behavior.
- [ ] Add Rust unit/build checks for the desktop shell and audio capability contracts.
- [ ] Add client/desktop checks to CI when Node/Rust dependency installation is available.
- [ ] Run Python compile/tests against the final desktop-refactor state.
- [ ] Run `npm install`/typecheck/Expo doctor and validate the web export.
- [ ] Run Cargo checks for `crates/audio-core`, `crates/audio-windows`, and `apps/desktop/src-tauri`.
- [ ] Validate the Expo web export consumed by Tauri.
- [ ] Validate Tauri development/build packaging on Windows.
- [ ] Validate physical microphone/render endpoint enumeration on the development Windows machine.
- [ ] Validate actual WASAPI loopback capture.
- [ ] Validate a real virtual-microphone endpoint/output path before marking system-wide conference integration complete.
- [x] Keep plan in `in-progress` while executable/hardware/platform validation remains outstanding.

Validation note: the current execution container could not clone GitHub (`Could not resolve host: github.com`), so no local Node/Rust/Python build result is being inferred from source edits.

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
- [ ] The desktop shell launches as an installable application and can discover/control a packaged local runtime.
- [ ] Windows microphone and loopback audio work through native code.
- [ ] A real virtual-microphone path is validated or explicitly separated as an external driver/install prerequisite.
- [ ] The local runtime no longer serves `apps/desktop-companion/model-manager` as the primary product UI.
- [ ] The legacy `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` are deleted because their causes were corrected/replaced.
- [ ] The misleading `desktop-companion` directory is removed or archived under an explicitly legacy path.
- [ ] Documentation and commands reference the desktop-first shared-client architecture.
- [ ] Move this plan to `.agents/plans/completed/` only after desktop functional parity and required platform validation are complete.
