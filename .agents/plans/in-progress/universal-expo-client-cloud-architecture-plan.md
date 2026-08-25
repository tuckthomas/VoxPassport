# Universal Expo Client + VoxPassport Platform Architecture Plan

Status: In progress — canonical Expo migration, account/auth foundations, cross-platform native desktop audio, hosted Windows WDK build/staging, hosted macOS HAL crossover, and headless Linux PipeWire crossover are complete. Remaining current-phase work is physical Windows/macOS/conferencing acceptance plus explicitly deferred hosted/mobile features. Tauri is not part of the architecture.

Purpose: Replace the prototype browser-only frontend with one maintainable Expo + React Native + React Native Web client, preserve free local/self-hosted inference, support optional PostgreSQL-backed accounts/cloud features, add provider-agnostic direct speech translation, and provide desktop system-audio integration through the local runtime/native audio layer rather than a second desktop UI framework. Android/iOS remain future targets of the same Expo client.

## Product architecture decision

- [x] Use Expo + React Native + React Native Web as the canonical product client architecture.
- [x] Use Expo Router for universal file-based navigation.
- [x] Target Expo SDK 57 / React Native 0.86 / React 19.2.x as the current implementation baseline.
- [x] Keep the browser extension separate because it is genuinely browser-specific integration code.
- [x] Keep `apps/client` as the one product UI for Android, iOS, web/PWA, and desktop-oriented workflows.
- [x] Do **not** use Tauri or create a second desktop UI shell.
- [x] Keep desktop as the immediate workflow priority without changing the canonical Expo architecture.
- [x] Put native system audio, virtual microphone, loopback, and driver work behind runtime/native contracts rather than UI-framework IPC.
- [x] Keep local/self-hosted use available without VoxPassport-hosted infrastructure or an account.
- [x] Defer mobile call-transport implementation while preserving mobile-compatible client contracts.
- [x] Prefer a future VoxPassport-native calling/WebRTC path on mobile instead of assuming arbitrary cross-app microphone injection.

## Deployment and account boundary

- [x] Add deployment configuration through `config/deployment.json` plus real `.env` loading.
- [x] Environment variables override deployment JSON.
- [x] Add `VOXPASSPORT_LOCAL_ONLY`, `VOXPASSPORT_ACCOUNTS_ENABLED`, and `VOXPASSPORT_ABUSE_CONTROLS_ENABLED` semantics.
- [x] Make `local_only=true` force accounts and hosted abuse/rate controls off.
- [x] Expose deployment/account capability state through the versioned runtime bootstrap so one Expo build adapts to local or multi-user deployments.
- [x] Hide Account/Login/Signup navigation and provider-account controls when accounts are disabled.
- [x] Make direct `/login`, `/signup`, and `/account` navigation unavailable when the connected runtime disables accounts.
- [x] Keep account identity separate from the local inference daemon.
- [x] Add PostgreSQL **18.6** account-service development/CI infrastructure.
- [x] Add PostgreSQL users, rotating refresh sessions, and encrypted per-user provider credentials with Alembic migrations.
- [x] Add email/password signup, login, logout, logout-all, `me`, and password change. No social auth yet.
- [x] Use Argon2id password hashing.
- [x] Use short-lived access JWTs and opaque rotating refresh tokens whose hashes, not raw tokens, are stored in PostgreSQL.
- [x] Use HttpOnly refresh cookies for web and Expo SecureStore for native refresh tokens; keep access tokens memory-only.
- [x] Encrypt stored provider API credentials at rest with AES-GCM and never return the secret through list APIs.
- [x] Disable account-service auth routes when auth/local-only configuration disables accounts.
- [x] Add application-layer auth rate controls for non-local deployments; explicitly bypass them in local-only mode.
- [ ] Add email verification later when hosted account onboarding requires it.
- [ ] Add password-reset email/token workflow later.
- [ ] Add OAuth/social identity providers later without changing the local-only deployment boundary.

## Desktop use of Expo

- [x] Treat the Expo web/PWA target as the desktop-facing product UI during this phase.
- [x] Keep communication-platform integration independent from inference-provider selection.
- [x] Keep Zoom/Meet/Teams/etc. plugins/extensions optional for richer UX rather than required core transport.
- [x] Preserve reusable native audio components independently of any desktop shell framework.
- [x] Expose native desktop audio capabilities to the Expo client through stable local-runtime APIs/services.
- [x] Implement Windows microphone capture in the native audio layer.
- [x] Implement Windows WASAPI loopback capture in the native audio layer.
- [x] Implement bounded native WASAPI render output.
- [x] Add stable MMDevice device/routing selection endpoints to the local runtime and Expo Runtime & Audio screen.
- [x] Implement a VoxPassport-owned Windows virtual-audio driver source/build/install/validation path based on a pinned Microsoft Simple Audio Sample substrate.
- [x] Keep the driver source substrate pinned instead of tracking Microsoft `main` dynamically.
- [x] Add a real driver-side bounded render-to-capture PCM ring: `VoxPassport Translation Sink` -> kernel ring -> `VoxPassport Virtual Microphone`.
- [x] Add deterministic end-to-end cable validation that renders known PCM and requires non-silent PCM from the capture endpoint.
- [x] Implement a macOS CoreAudio helper and libASPL HAL virtual-device pair behind the same native-media boundary.
- [x] Build/install/enumerate the macOS HAL plug-in on a hosted macOS runner and validate deterministic `Translation Sink -> Virtual Microphone` PCM crossover.
- [x] Add macOS native PCM normalization so provider-shape PCM can be converted at the native boundary before the fixed HAL format.
- [x] Implement Linux PipeWire/PipeWire-Pulse endpoint enumeration, capture/render helper support, and persistent VoxPassport virtual sink/source configuration.
- [x] Build/sign/stage the Windows virtual driver in hosted WDK-capable CI.
- [ ] Test-sign/install the staged Windows virtual driver on the development Windows machine under its allowed driver policy.
- [ ] Run `scripts/validate_virtual_audio.py` successfully against the installed Windows endpoint pair.
- [ ] Validate desktop PWA/client plus native helper/runtime startup together on the target Windows machine.
- [ ] Select `VoxPassport Virtual Microphone` in at least one real conferencing application and confirm translated audio is received.
- [ ] Complete explicit echo/feedback ownership validation under real conference routing.
- [ ] Validate real macOS microphone/output/TCC and conferencing behavior on a physical Mac.

## Provider/model architecture

- [x] Keep the existing modular `VAD -> ASR -> NMT -> TTS` pipeline.
- [x] Define `DIRECT_SPEECH_TRANSLATION` as a separate first-class capability.
- [x] Add provider/strategy metadata independently from communication transport.
- [x] Add a provider-agnostic direct-speech translation catalog and manifest-driven adapter entrypoints.
- [x] Register Gemini 3.5 Live Translate declaratively as a BYO-API direct-speech strategy.
- [x] Keep Google/Gemini-specific wire behavior out of generic Expo UI/session contracts.
- [x] Distinguish execution modes such as local, BYO API, self-hosted/private, and managed cloud.
- [x] Define the executable streaming session interface for direct-speech strategies.
- [x] Add bounded session/event queues and backpressure.
- [x] Implement Gemini Live Translate setup/audio/transcript/translated-audio/interruption/goAway mapping behind the provider-neutral interface.
- [x] Prevent API-key leakage through provider connection exceptions.
- [x] Add transactional modular/direct strategy activation with candidate validation and rollback.
- [x] Persist and restore the selected translation strategy safely.
- [x] Block strategy/routing mutation while a live native session is active.
- [ ] Add additional direct-speech providers using the same manifest/adapter contract.

## Repository organization

- [x] Make `apps/client/` the canonical universal product frontend.
- [x] Keep `apps/browser-extension/` for browser-specific integration only.
- [x] Retire the prototype `apps/desktop-companion/model-manager` product UI after Expo parity.
- [x] Remove the unintended `apps/desktop/` Tauri shell.
- [x] Remove Tauri dependencies and IPC bridge code from `apps/client`.
- [x] Add architecture tests that fail if Tauri dependencies/references or a Tauri desktop shell are reintroduced without an explicit architecture change.
- [x] Add architecture tests that fail if the retired desktop Studio/fix-layer product UI is reintroduced.
- [x] Add `docs/development/repository-layout.md` with ownership/routing rules.
- [x] Keep native audio code in platform-owned runtime/native components, independent of Expo UI choices.
- [x] Keep Windows driver development under `drivers/windows/virtual-audio` and generated Microsoft/build trees out of source control.
- [x] Preserve Microsoft MS-PL notices/license when materializing the pinned driver substrate.
- [x] Remove the stale nonexistent Rust `ipc-client` workspace member instead of preserving dead topology.
- [x] Remove `apps/desktop-companion` entirely after moving reusable brand assets to `apps/client/assets` and changing the runtime root route to the canonical Expo client.

## Expo client foundation

- [x] Scaffold `apps/client` as a TypeScript Expo project.
- [x] Configure Expo Router and React Native Web.
- [x] Add strict TypeScript configuration.
- [x] Add `expo-audio` and microphone permission configuration without enabling background recording by default.
- [x] Add cross-platform settings storage.
- [x] Add reusable design tokens, screen layout, and card primitives.
- [x] Create thin Expo routes backed by feature-oriented `src/features/...` modules.
- [x] Add Translator, Models & Engines, Voice Profiles, Runtime/Diagnostics, Settings, Login, Signup, and Account routes.
- [x] Add a typed text-translation workflow against the selected runtime target.
- [x] Add typed model and voice-profile rendering from backend APIs rather than legacy global-array mutation.
- [x] Add live translation engine selection, validation/activation, Full Duplex / Outbound / Inbound modes, Start/Stop, status, counters, and inbound/outbound caption display.
- [x] Keep raw PCM out of Expo/React state; the UI controls only low-frequency runtime/session state.
- [x] Add voice enrollment/preview/save/activation/delete workflows using typed API services.
- [x] Add model install/progress/activation/uninstall workflows using typed services and backend-owned installability/reason metadata.

## Client runtime abstraction

- [x] Define typed runtime/session contracts.
- [x] Define a `RuntimeTarget` abstraction with local, self-hosted, and future cloud modes.
- [x] Centralize active runtime URL selection in `RuntimeTargetContext`.
- [x] Centralize HTTP access in `VoxPassportApi` and feature access through `useVoxPassportApi()`.
- [x] Add a dedicated low-frequency `LiveTranslationApi`; raw media remains runtime/native.
- [x] Support configurable local and self-hosted runtime URLs.
- [x] Keep feature screens independent from localhost, AWS, GPU process, worker-port, and native implementation details.
- [ ] Add authenticated self-hosted/cloud session allocation when managed cloud implementation resumes.

## Local runtime compatibility

- [x] Preserve the Python runtime as owner of models, GPU processes, inference supervision, TTS runtime management, and local session orchestration.
- [x] Preserve existing local REST APIs during migration.
- [x] Do not make Expo components start/manage individual Python/CUDA workers.
- [x] Add a versioned `/api/client/bootstrap` endpoint exposing runtime/session/deployment capability URLs generically.
- [x] Add explicit restricted CORS handling for approved Expo web/PWA localhost/configured origins.
- [x] Protect the runtime resource WebSocket with the same origin policy.
- [x] Add native-audio capability/status/device endpoints.
- [x] Add stable-ID audio routing configuration endpoints.
- [x] Add native helper subprocess boundary for realtime capture/render and binary `VPF1` PCM frames.
- [x] Keep raw high-frequency PCM on subprocess/native media paths rather than REST/JSON/base64/UI IPC.
- [x] Add `runtime/inference/server/integrated_main.py` to compose runtime inference with strategy/native-media services without another UI framework.
- [x] Make `run.bat` launch the integrated runtime and canonical Expo web client together for local development.
- [x] Make `install.bat` install the canonical Expo client dependencies in addition to the Python runtime environment.
- [x] Restore/unload direct strategy state through integrated daemon startup/shutdown.
- [x] Run the degraded-mode scheduler only while the modular cascade owns inference.

## Desktop native audio architecture

- [x] Shared protocol distinguishes physical mic, remote conference, outbound translated audio, inbound translated audio, virtual mic, and local monitor buses.
- [x] Audit the old Python pipeline: `AudioBus.VIRTUAL_MIC` was only a logical bus and did not create an OS microphone.
- [x] Define portable native audio endpoint/platform contracts in `audio-core`.
- [x] Implement Windows Core Audio endpoint enumeration with stable MMDevice IDs, friendly names, and default-device detection.
- [x] Implement physical microphone WASAPI capture.
- [x] Implement WASAPI system-loopback capture from render endpoints.
- [x] Implement bounded WASAPI render output.
- [x] Implement native-audio-to-Python subprocess transport with a fixed binary PCM frame contract.
- [x] Implement persistent endpoint routing for mic, loopback, monitor, virtual render side, and virtual capture side.
- [x] Distinguish virtual-microphone `configured` from human/hardware `validated`.
- [x] Implement direct full-duplex media control: mic -> provider -> virtual render and conference loopback -> reverse-language provider -> local monitor.
- [x] Add hardware-independent fake capture/provider/render tests for the full-duplex controller.
- [x] Add Windows helper detection that reports virtual-microphone capability only when both VoxPassport OS endpoints enumerate.
- [x] Add pinned Windows virtual-driver preparation script with guarded upstream patches.
- [x] Add WDK build, test-install, and uninstall scripts without silently changing Secure Boot.
- [x] Add end-to-end virtual cable PCM validator.
- [x] Add a macOS CoreAudio helper using the same VPF1 subprocess contract and stable CoreAudio endpoint UIDs.
- [x] Add a macOS HAL virtual-audio plug-in and hosted-runner install/enumeration/crossover validation.
- [x] Add a Linux PipeWire/PipeWire-Pulse helper implementation and virtual sink/source scripts.
- [x] Compile the Windows kernel driver fully with WDK on the hosted Windows CI runner and verify the staged INF/SYS package.
- [ ] Test-sign/install the Windows driver under the development machine's allowed Windows driver policy.
- [ ] Validate real Windows WASAPI endpoint formats and capture/render behavior on hardware.
- [ ] Validate the Windows virtual cable with the deterministic PCM test and a conferencing application.
- [ ] Validate real macOS physical endpoints, TCC permissions, signing/notarization, and conferencing behavior.

## Mobile deferred phase

- [x] Preserve Android/iOS as targets of `apps/client` rather than introducing separate client frameworks.
- [x] Defer mobile calling implementation while desktop workflow is established.
- [x] Prefer a future VoxPassport-native/WebRTC call transport on mobile.
- [ ] Revisit iOS microphone injection only if Apple permits the intended translation use case.
- [ ] Revisit Android cross-app injection only if Google exposes a sanctioned public capability.

## Fix-layer cleanup rule

For every legacy `*-fixes.js` behavior:

- [x] If it compensated for broken/obsolete original behavior: correct the owner implementation and delete the patch.
- [x] If it existed only for compatibility with a removed design: delete it entirely.
- [x] If it implemented enduring domain behavior: reimplement it in the proper Expo/client/backend abstraction instead of copying the patch.
- [x] If it hard-coded metadata now available from APIs/manifests: make the Expo UI data-driven and delete the hard-coded logic.
- [x] If it was temporary migration logic: finish the migration and delete it.
- [x] Do not create new `*-fixes.js`, iframe `eval()` bridges, hidden compatibility elements, fetch monkey-patches, Tauri bridges, or duplicate desktop screens.

## Legacy patch-specific migration

- [x] New model catalog rendering uses typed backend data rather than legacy global arrays.
- [x] New voice-profile rendering uses backend state rather than legacy DOM/global state.
- [x] New text translation constructs the correct request at its typed API source instead of relying on fetch interception.
- [x] Replace voice enrollment/synthesis request interception with typed Expo/backend workflows.
- [x] Eliminate the hidden `studioCloneModelSelect` compatibility sentinel by retiring the prototype Studio.
- [x] Retire Silero v4-to-v6 UI repair; aliases/catalog/runtime metadata own canonical model identity.
- [x] Replace `stack-upgrade-fixes.js` hard-coded install exceptions with generic backend `installable` / `installation_reason` metadata.
- [x] Delete `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` after moving required behavior to its owning implementation.

## VoxPassport Cloud — optional/later

- [x] Keep hosted cloud optional rather than required for personal/local use.
- [x] Preserve the control-plane/media-plane design: control plane allocates/authenticates; latency-sensitive media can stream directly to allocated workers/providers when safe.
- [x] Build account/auth infrastructure independently so local-only deployments can disable it entirely.
- [ ] Create the managed cloud allocation/control-plane service only when hosted service implementation resumes.
- [ ] Add worker allocation, short-lived media credentials, usage accounting, and pricing as server-side concerns.
- [ ] Do not block desktop/local Expo completion on hosted GPU infrastructure.

## Tests and validation

- [x] Add static architecture tests preventing new patch-history files in `apps/client`.
- [x] Add architecture tests preventing Tauri dependencies/references and `apps/desktop` reintroduction.
- [x] Add architecture tests preventing the retired legacy Studio/fix-layer UI from returning.
- [x] Add direct translation provider-catalog, loader, session, Gemini wire-protocol, and transactional strategy-manager tests.
- [x] Add runtime bootstrap/CORS/deployment tests.
- [x] Add native audio bridge and full-duplex controller tests.
- [x] Add PostgreSQL 18.6 account-service CI with migrations and database-backed auth/encryption/session tests.
- [x] Add local-only/account-disabled/rate-control tests.
- [x] Add Expo TypeScript typecheck and web export CI.
- [x] Add Windows Rust audio/helper tests.
- [x] Add Linux Rust audio/helper tests and a headless PipeWire live-validation workflow.
- [x] Add macOS Swift helper + HAL build CI.
- [x] Add hosted macOS HAL install/enumeration/deterministic crossover validation.
- [x] Add virtual-driver overlay static tests.
- [x] Add Windows CI preparation of the pinned Microsoft driver substrate and verify guarded patches/license/endpoint names.
- [x] Resolve the obsolete `Runtime Integrity` failure tracked as run `32773745017`; later integrity/account/Expo/macOS/Linux compile jobs have passed after the migration fixes.
- [x] Complete the hosted Windows WDK kernel-driver compile and staged INF/SYS verification.
- [x] Make the headless Linux helper crossover validation green after the PipeWire-Pulse media-boundary change.
- [ ] Validate Expo web/PWA in a browser on the target Windows machine.
- [ ] Validate Windows endpoint enumeration/capture/loopback on real hardware.
- [ ] Validate `VoxPassport Translation Sink` -> driver bridge -> `VoxPassport Virtual Microphone` with `scripts/validate_virtual_audio.py` on Windows.
- [ ] Validate the actual Windows virtual microphone with a conferencing application.
- [ ] Validate physical Mac microphone/output permission and conferencing behavior.
- [x] Keep this plan in `in-progress` while platform/hardware validation remains outstanding.

## Current desktop acceptance path

```text
                         Expo / React Native Web client
                                  |
                                  | low-frequency typed control/session APIs
                                  v
                      VoxPassport Integrated Local Runtime
                                  |
                 +----------------+----------------+
                 |                                 |
                 v                                 v
      Modular VAD -> ASR -> NMT -> TTS    Direct speech providers
                 |                                 |
                 +----------------+----------------+
                                  |
                                  v
                       Native audio service boundary
                                  |
            +---------------------+----------------------+
            |                     |                      |
            v                     v                      v
      Windows WASAPI         macOS CoreAudio       Linux PipeWire/
      + WDM virtual mic      + HAL virtual mic     PipeWire-Pulse pair
            |                     |                      |
            +---------------------+----------------------+
                                  |
                                  v
                   conferencing / softphone endpoint
```

The UI remains Expo. Native platform audio and virtual-device implementations are services behind the runtime boundary, not separate application shells.

## Migration completion criteria

- [x] The Expo client covers the production workflows expected from the retired prototype Studio, including translation, strategy/session controls, audio routing, models, voice profiles, settings, and optional account flows.
- [ ] Desktop live translation is physically validated through runtime/native audio contracts without Tauri.
- [ ] The VoxPassport Windows virtual driver builds, installs, and passes deterministic PCM crossover validation on a physical Windows system.
- [ ] `VoxPassport Virtual Microphone` is validated with at least one conferencing application on Windows.
- [x] The normal local development command launches Expo as the primary UI; the runtime no longer depends on the old Studio application.
- [x] `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` are deleted because their causes were corrected/replaced.
- [ ] Remove the remaining temporary `apps/desktop-companion` URL-compatibility launcher/assets after the runtime `/manager` redirect is eliminated.
- [x] Documentation and local development commands consistently describe the Expo architecture.
- [ ] Move this plan to `.agents/plans/completed/` only after required physical platform validation is complete; explicitly deferred hosted/mobile features may remain follow-on work.
