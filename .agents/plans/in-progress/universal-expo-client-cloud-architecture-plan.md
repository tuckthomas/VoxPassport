# Universal Expo Client + VoxPassport Cloud Architecture Plan

Status: In progress

Purpose: Replace the prototype browser-only frontend architecture with a maintainable universal client built on Expo + React Native + React Native Web, while preserving the existing local inference runtime and defining VoxPassport Cloud as a control plane that allocates direct low-latency inference workers. The migration must correct underlying frontend defects rather than simply relocating `*-fixes.js` compatibility patches.

## Product architecture decision

- [x] Use Expo + React Native + React Native Web as the primary client architecture for Android, iOS, and web/PWA.
- [x] Use Expo Router for universal file-based navigation.
- [x] Target Expo SDK 57 / React Native 0.86 / React 19.2.x as the current implementation baseline.
- [x] Keep the browser extension separate because it is genuinely browser-specific integration code.
- [x] Do not add a dedicated desktop application shell unless a concrete future capability requires one.
- [x] Keep the web client usable with the local VoxPassport runtime for local/private inference.
- [x] Treat Android/iOS as first-class product clients rather than wrappers around the legacy HTML application.

## Cloud topology

- [x] Separate VoxPassport Cloud control-plane responsibilities from latency-sensitive media/inference transport.
- [x] Cloud control plane owns authentication, subscription/entitlement state, region selection, worker allocation, session policy, short-lived worker credentials, and usage accounting.
- [x] Client receives an allocated worker endpoint and short-lived session credential from the control plane.
- [x] Client streams audio/captions/synthesized media directly to/from the allocated inference worker by default.
- [x] Keep relay/proxy mode as an explicit fallback for networks or privacy/security configurations that require it.
- [x] Keep provider/model implementation details behind worker capabilities rather than embedding AWS/model assumptions in the client.
- [x] Design pricing/metering so hosted usage can include configurable margin above infrastructure cost without exposing provider cost internals to the client.

## Repository organization

- [ ] Make `apps/client/` the canonical universal product frontend.
- [ ] Remove the misleading `apps/desktop-companion` naming from the long-term architecture.
- [ ] Keep `apps/browser-extension/` for the browser extension only.
- [ ] Create a clearly labeled legacy frontend location during migration rather than pretending the old page remains the architectural target.
- [ ] Document ownership boundaries so humans and AI agents can infer where client, local runtime, cloud control plane, protocols, workers, and browser integration live.
- [ ] Delete superseded pending frontend/mobile plans once their still-relevant requirements are incorporated here.

## Expo client foundation

- [ ] Scaffold `apps/client` as a TypeScript Expo SDK 57 project.
- [ ] Configure Expo Router and typed routes.
- [ ] Configure React Native Web / Metro web output.
- [ ] Add `expo-audio` for cross-platform microphone capture/playback capability.
- [ ] Add native microphone permission configuration without enabling background recording by default.
- [ ] Create shared visual primitives/theme rather than another giant monolithic page.
- [ ] Create feature-oriented routes/screens for Translator, Models, Voice Profiles, Runtime/Diagnostics, and Settings.
- [ ] Keep platform-specific implementation files narrowly scoped (`*.native.ts`, `*.web.ts`) when behavior genuinely differs.

## Client runtime abstraction

- [ ] Define a client-side `RuntimeTarget` abstraction with at least `local` and `cloud` modes.
- [ ] Keep screen/components independent from localhost, AWS, model process, and worker-port assumptions.
- [ ] Centralize HTTP/API access in one typed API client.
- [ ] Centralize live session/media transport behind a session service.
- [ ] Define typed bootstrap/status/model/voice/session contracts.
- [ ] Support local runtime URL configuration for self-hosted/local use.
- [ ] Support VoxPassport Cloud base URL configuration for hosted use.
- [ ] Keep access/session tokens out of ordinary logs and UI state serialization.

## Local runtime compatibility

- [ ] Add a versioned client/bootstrap endpoint to the local runtime so the Expo client can discover capabilities and websocket endpoints generically.
- [ ] Add explicit CORS handling for approved localhost development/web origins instead of relying on same-origin legacy HTML.
- [ ] Preserve existing local APIs during migration.
- [ ] Preserve the local runtime as the component that owns models, GPU processes, audio routing, and TTS supervision.
- [ ] Do not make the Expo web client responsible for starting Python/CUDA workers.

## Session protocol

- [ ] Add a versioned shared session protocol/schema package.
- [ ] Define session allocation request/response contracts.
- [ ] Define worker capability negotiation.
- [ ] Include source/target languages, requested features, codecs/formats, correlation/session IDs, and protocol version.
- [ ] Define short-lived worker credential metadata and expiration.
- [ ] Define media/control event envelopes for audio, partial/final captions, translations, TTS audio, state, latency, and errors.
- [ ] Keep signaling/control messages separate from binary media frames.
- [ ] Permit `direct_worker` and `relay` media modes.

## VoxPassport Cloud control-plane scaffold

- [ ] Create a separately packaged `services/cloud-control-plane` Python service.
- [ ] Add `/health` and version endpoints.
- [ ] Add session allocation endpoint using the shared v1 session contract.
- [ ] Keep worker selection behind an allocator interface.
- [ ] Add an in-memory development worker registry/allocator without hard-coding AWS in business logic.
- [ ] Issue signed short-lived worker session credentials.
- [ ] Return worker endpoint, media mode, protocol version, expiration, and pricing/metering metadata.
- [ ] Add configurable cost-plus pricing policy with minimum margin support as a service-side concern.
- [ ] Never trust client-reported usage for billing; reserve worker/control-plane usage reporting as the authoritative future path.
- [ ] Mark real authentication, payment provider integration, durable worker registry, AWS orchestration, and production secrets as later deployment work.

## Fix-layer cleanup rule

For every legacy `*-fixes.js` behavior, classify it before touching it:

- [ ] If it compensates for broken/obsolete original behavior: correct the owner implementation and delete the patch.
- [ ] If it exists only for compatibility with a removed design: delete it entirely.
- [ ] If it implements enduring domain behavior: reimplement that behavior in the proper Expo/client/backend abstraction, not by copying the patch.
- [ ] If it hard-codes metadata now available from APIs/manifests: make the UI data-driven and delete the hard-coded logic.
- [ ] If it is temporary migration logic: finish the migration and delete it.
- [ ] Do not create new `*-fixes.js`, iframe `eval()` bridges, hidden compatibility elements, or fetch monkey-patches.

## Legacy patch-specific migration

- [ ] Replace `runtime-fixes.js` model-state synchronization with typed API/store state in the Expo client.
- [ ] Replace `runtime-fixes.js` request interception by constructing correct API requests at their source.
- [ ] Eliminate the hidden `studioCloneModelSelect` timer/model compatibility sentinel rather than recreating it.
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

- [ ] Add static architecture tests that forbid new `*-fixes.js` files in the canonical client.
- [ ] Add tests/validation for shared session schema examples.
- [ ] Add cloud control-plane unit tests for allocation, credential expiration, pricing, and invalid requests.
- [ ] Add local-runtime contract tests for client bootstrap/CORS behavior.
- [ ] Add TypeScript typecheck/lint commands for `apps/client`.
- [ ] Add Expo project validation (`expo-doctor`) to documented local validation.
- [ ] Add client checks to CI when Node package installation is available.
- [ ] Run Python compile/tests available in this execution environment.
- [ ] Run/install Expo dependencies and TypeScript validation in a connected development environment.
- [ ] Validate web build in a browser.
- [ ] Validate Android development build on a physical/emulated device.
- [ ] Validate iOS development build on macOS/Xcode/device or simulator.

## Migration completion criteria

The migration is complete when:

```text
Android / iOS / Web
        -> one Expo / React Native client

Local/private mode
        -> client -> VoxPassport Local Runtime -> local inference

Hosted mode
        -> client -> VoxPassport Cloud control plane
        -> allocated worker + short-lived credential
        -> client <-> worker direct media stream

Legacy HTML/JS patch architecture
        -> removed
```

- [ ] The Expo client covers the production workflows currently expected from the legacy Studio.
- [ ] The local runtime no longer needs to serve `apps/desktop-companion/model-manager` as the primary UI.
- [ ] The legacy `runtime-fixes.js`, `engine-catalog-fixes.js`, and `stack-upgrade-fixes.js` files are deleted because their causes were corrected/replaced, not merely renamed.
- [ ] The misleading `desktop-companion` directory is removed.
- [ ] All relevant documentation/screenshots/commands reference the new client architecture.
- [ ] If full parity/mobile validation requires the personal development environment, keep this plan in `in-progress` and record the exact remaining checks.
- [ ] Move this plan to `.agents/plans/completed/` only after functional parity and required platform validation are complete.
