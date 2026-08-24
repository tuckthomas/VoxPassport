# Universal Expo Client + VoxPassport Platform Architecture Plan

Status: In progress — source-level desktop/live-audio/auth implementation is substantially complete; Windows driver/hardware validation and legacy Studio parity remain. Tauri is not part of the architecture.

Purpose: Replace the prototype browser-only frontend with one maintainable Expo + React Native + React Native Web client, preserve free local/self-hosted inference, support optional PostgreSQL-backed accounts/cloud features, add provider-agnostic direct speech translation, and provide desktop system-audio integration through the local runtime/native audio layer rather than a second desktop UI framework. Android/iOS remain future targets of the same Expo client.

## Product architecture decision

- [x] Use Expo + React Native + React Native Web as the canonical product client architecture.
- [x] Use Expo Router for universal file-based navigation.
- [x] Target Expo SDK 57 / React Native 0.86 / React 19.2.x as the current implementation baseline.
- [x] Keep the browser extension separate because it is genuinely browser-specific integration code.
- [x] Keep `apps/client` as the one product UI for Android, iOS, web/PWA, and desktop-oriented workflows.
- [x] Do **not** use Tauri or create a second desktop UI shell.
- [x] Keep desktop as the immediate workflow priority without changing the canonical Expo architecture.
- [x] Put Windows system audio, virtual microphone, loopback, and driver work behind runtime/native contracts rather than UI-framework IPC.
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
- [x] Preserve reusable Rust audio crates independently of any desktop shell framework.
- [x] Expose native desktop audio capabilities to the Expo client through stable local-runtime APIs/services.
- [x] Implement Windows microphone capture in the native audio layer.
- [x] Implement Windows WASAPI loopback capture in the native audio layer.
- [x] Implement bounded native WASAPI render output.
- [x] Add stable MMDevice device/routing selection endpoints to the local runtime and Expo Runtime & Audio screen.
- [x] Implement a VoxPassport-owned Windows virtual-audio driver source/build/install/validation path based on a pinned Microsoft Simple Audio Sample substrate.
- [x] Keep the driver source substrate pinned instead of tracking Microsoft `main` dynamically.
- [x] Add a real driver-side bounded render-to-capture PCM ring: `VoxPassport Translation Sink` -> kernel ring -> `VoxPassport Virtual Microphone`.
- [x] Add deterministic end-to-end cable validation that renders known PCM and requires non-silent PCM from the capture endpoint.
- [ ] Build/sign/install the virtual driver on the development Windows machine.
- [ ] Run `scripts/validate_virtual_audio.py` successfully against the installed endpoint pair.
- [ ] Validate desktop PWA/client plus native helper/runtime startup together on Windows.
- [ ] Select `VoxPassport Virtual Microphone` in at least one real conferencing application and confirm translated audio is received.
- [ ] Complete explicit echo/feedback ownership validation under real conference routing.

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
- [x] Keep `apps/desktop-companion/` explicitly legacy during migration.
- [x] Remove the unintended `apps/desktop/` Tauri shell.
- [x] Remove Tauri dependencies and IPC bridge code from `apps/client`.
- [x] Add architecture tests that fail if Tauri dependencies/references or a Tauri desktop shell are reintroduced without an explicit architecture change.
- [x] Add `docs/development/repository-layout.md` with ownership/routing rules.
- [x] Keep native audio code in `crates/audio-core` / `crates/audio-windows`, independent of Expo UI choices.
- [x] Keep Windows driver development under `drivers/windows/virtual-audio` and generated Microsoft/build trees out of source control.
- [x] Preserve Microsoft MS-PL notices/license when materializing the pinned driver substrate.
- [x] Remove the stale nonexistent Rust `ipc-client` workspace member instead of preserving dead topology.
- [ ] Move/rename the legacy HTML frontend only after the Expo client reaches sufficient parity.

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
- [ ] Add voice enrollment/preview/activation workflows using typed API services.
- [ ] Add model activation/install/uninstall workflows using typed services and backend-owned metadata.

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
- [x] Add a native helper subprocess boundary for realtime capture/render and binary `VPF1` PCM frames.
- [x] Keep raw high-frequency PCM on subprocess/native media paths rather than REST/JSON/base64/UI IPC.
- [x] Add `runtime/inference/server/integrated_main.py` to compose the legacy daemon with strategy/native-media services without another UI framework.
- [x] Make `run.bat` launch the integrated runtime entrypoint.
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
- [ ] Compile the kernel driver with WDK on the Windows development machine or a WDK-capable CI runner.
- [ ] Test-sign/install the driver under the development machine's allowed Windows driver policy.
- [ ] Validate real WASAPI endpoint formats and capture/render behavior on hardware.
- [ ] Validate the virtual cable with the deterministic PCM test and a conferencing application.

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
- [x] Build account/auth infrastructure independently so local-only deployments can disable it entirely.
- [ ] Create the managed cloud allocation/control-plane service only when hosted service implementation resumes.
- [ ] Add worker allocation, short-lived media credentials, usage accounting, and pricing as server-side concerns.
- [ ] Do not block desktop/local Expo completion on hosted GPU infrastructure.

## Tests and validation

- [x] Add static architecture tests preventing new patch-history files in `apps/client`.
- [x] Add architecture tests preventing Tauri dependencies/references and `apps/desktop` reintroduction.
- [x] Add direct translation provider-catalog, loader, session, Gemini wire-protocol, and transactional strategy-manager tests.
- [x] Add runtime bootstrap/CORS/deployment tests.
- [x] Add native audio bridge and full-duplex controller tests.
- [x] Add PostgreSQL 18.6 account-service CI with migrations and database-backed auth/encryption/session tests.
- [x] Add local-only/account-disabled/rate-control tests.
- [x] Add Expo TypeScript typecheck and web export CI.
- [x] Add Windows Rust audio/helper tests.
- [x] Add virtual-driver overlay static tests.
- [x] Add Windows CI preparation of the pinned Microsoft driver substrate and verify the guarded patches/license/endpoint names without requiring WDK installation.
- [ ] Observe and fix the current pull-request CI validation run (`Runtime Integrity` run `32773745017`).
- [ ] Compile the WDK kernel driver.
- [ ] Validate Expo web/PWA in a browser on the target Windows machine.
- [ ] Validate Windows endpoint enumeration/capture/loopback on real hardware.
- [ ] Validate `VoxPassport Translation Sink` -> driver bridge -> `VoxPassport Virtual Microphone` with `scripts/validate_virtual_audio.py`.
- [ ] Validate the actual virtual microphone with a conferencing application.
- [x] Keep this plan in `in-progress` while platform/hardware validation and legacy parity remain outstanding.

## Current desktop acceptance path

```text
Expo / React Native Web client
        |
        | low-frequency typed control/session APIs
        v
VoxPassport Integrated Local Runtime
        |
        +--> Local modular VAD -> ASR -> NMT -> TTS
        |
        +--> Direct speech provider adapters (Gemini first)
        |
        +--> Native Windows audio helper (binary PCM subprocess transport)
                    |
                    +--> physical microphone WASAPI capture
                    +--> conference/system WASAPI loopback capture
                    +--> translated local-monitor WASAPI render
                    +--> VoxPassport Translation Sink
                              |
                              v
                         bounded WDM PCM ring
                              |
                              v
                         VoxPassport Virtual Microphone
                              |
                              v
                    Meet / Zoom / Teams / Discord / softphone
```

The UI remains Expo. Native Windows audio and the virtual driver are implementation services behind the runtime boundary, not a second application shell.

## Migration completion criteria

- [ ] The Expo client covers the production workflows currently expected from the legacy Studio.
- [ ] Desktop live translation works through runtime/native audio contracts without Tauri.
- [ ] The VoxPassport virtual driver builds, installs, and passes deterministic PCM crossover validation on Windows.
- [ ] `VoxPassport Virtual Microphone` is validated with at least one conferencing application.
- [ ] The local runtime no longer needs to serve `apps/desktop-companion/model-manager` as the primary UI.
- [ ] `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` are deleted because their causes were corrected/replaced.
- [ ] The misleading `desktop-companion` directory is removed or archived under an explicitly legacy path.
- [ ] Documentation and commands consistently describe the Expo architecture.
- [ ] Move this plan to `.agents/plans/completed/` only after functional parity and required platform validation are complete.
