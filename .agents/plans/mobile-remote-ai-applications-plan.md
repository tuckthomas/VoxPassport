# Standalone Android and iPhone Applications Plan

## Purpose and product boundary

- [ ] Build standalone VoxPassport applications for Android and iPhone rather than treating the mobile experience as a wrapped desktop web page.
- [ ] Keep microphone capture, speaker playback, captions, controls, voice-profile selection, and connection state local to the phone.
- [ ] Run AI-heavy inference remotely in the initial release through a user-authorized VoxPassport inference service hosted on infrastructure such as AWS, a private GPU server, or a self-hosted endpoint.
- [ ] Design the client/server contract so the same mobile application can later run some or all inference locally as mobile hardware and model efficiency improve.
- [ ] Present the product honestly as remote inference initially; do not imply that audio is processed entirely on-device until that is verified for the selected configuration.
- [ ] Preserve the existing use cases: live translation with captions, standalone speech-to-text, text-to-text translation, voice cloning, and translated text-to-speech playback.

## Recommended application architecture

- [ ] Use a shared cross-platform core for protocol models, connection management, permissions, settings, capability negotiation, telemetry controls, and test fixtures.
- [ ] Use native Android and iPhone integrations for microphone routing, audio sessions, Bluetooth devices, notifications, background behavior, lock-screen behavior, and platform-specific permission flows.
- [ ] Keep the UI idiomatic to each platform while sharing product terminology, information hierarchy, accessibility rules, and visual language.
- [ ] Separate the mobile client into Capture, Transport, Session, Captions, Playback, Voice Profiles, Settings, and Diagnostics modules.
- [ ] Keep model files and inference runtimes out of the initial mobile application package unless a model is explicitly selected for local execution.
- [ ] Make the desktop application and mobile applications clients of a versioned session protocol instead of duplicating inference behavior in each UI.
- [ ] Keep all provider-specific AI implementation behind the remote inference service so mobile clients depend on capabilities and contracts, not model internals.

## Remote inference service

- [ ] Define a deployable remote inference service that can run on AWS GPU instances, a private GPU host, or a user-managed local server.
- [ ] Separate the public session gateway from GPU workers so authentication, rate limits, session routing, and connection recovery do not depend on a model process.
- [ ] Support worker pools with explicit capabilities for ASR, VAD, translation, TTS, voice cloning, diarization, and direct speech translation.
- [ ] Add model residency policies equivalent to the desktop Ready and On Demand modes.
- [ ] Keep model selection, model license metadata, hardware requirements, and provider terms on the server; send only compatible capability summaries to the client.
- [ ] Support per-session resource budgets so one mobile user cannot consume an entire GPU worker unintentionally.
- [ ] Add queueing, admission control, cancellation, timeouts, backpressure, and graceful degradation when GPU capacity is unavailable.
- [ ] Make the service horizontally scalable and stateless at the gateway layer, with session state stored only when required.
- [ ] Provide an optional self-hosted mode for users who do not want audio or voice data sent to a managed cloud service.

## Session and streaming protocol

- [ ] Define a versioned bidirectional streaming protocol for audio chunks, partial transcripts, final transcripts, translations, synthesized audio, captions, timing metadata, errors, and session state.
- [ ] Prefer secure WebSocket or WebRTC transport after measuring reliability, latency, firewall behavior, and mobile battery impact.
- [ ] Use WebRTC where direct low-latency media transport and network adaptation are more valuable than simple request/response semantics.
- [ ] Keep signaling, authentication, and inference control messages separate from encoded media frames.
- [ ] Include sequence numbers, timestamps, language codes, speaker/source identifiers, and correlation IDs on streamed events.
- [ ] Support reconnect and resume behavior without duplicating captions or replaying audio unexpectedly.
- [ ] Allow the client to cancel a phrase, clip, synthesis job, or entire session immediately.
- [ ] Negotiate audio sample rate, channel count, codec, packet size, target languages, caption mode, cloning mode, and supported output formats.
- [ ] Report end-to-end latency as capture-to-partial-caption, capture-to-final-translation, and capture-to-first-audio rather than one ambiguous latency number.
- [ ] Test the protocol on Wi-Fi, cellular, high-jitter networks, packet loss, captive portals, network transitions, and temporary offline periods.

## Audio capture and playback

- [ ] Use Android AudioRecord/AudioTrack or an approved native audio layer for predictable low-latency streaming.
- [ ] Use iPhone AVAudioSession and AVAudioEngine with explicit category, mode, route, interruption, and Bluetooth handling.
- [ ] Support wired headsets, Bluetooth headsets, speakerphone, car audio, USB audio, and platform audio route changes.
- [ ] Add echo cancellation, noise suppression, automatic gain control, and voice activity handling only where the platform and user settings permit them.
- [ ] Keep raw microphone audio in memory by default and discard it after transmission or local processing unless the user explicitly records or enrolls a voice profile.
- [ ] Make voice-profile enrollment an explicit recording workflow with consent, retention, deletion, and export controls.
- [ ] Prevent translated playback from being re-captured as source speech through echo-aware routing and stream ownership.
- [ ] Provide a fixed-clip workflow that records locally, uploads only the required audio, receives translated text/audio, and lets the user download or share the result.
- [ ] Preserve original and translated clip metadata so users can identify language, voice profile, model policy, and processing location.

## Voice cloning and TTS boundaries

- [ ] Keep voice-profile creation, reference-audio upload, consent, and deletion explicit in the mobile UX.
- [ ] Allow a profile to be represented by an engine-agnostic identity while the remote service selects a compatible cloning backend.
- [ ] Never silently substitute another user's profile or a stock voice when cloning is unavailable.
- [ ] Show whether a generated result used cloned voice, stock TTS, or a degraded fallback.
- [ ] Add configurable speech rate, clause length, output language, and clarity settings to the mobile client once the shared configuration schema supports them.
- [ ] Preserve pitch when applying any server-side or client-side speech-rate adjustment.
- [ ] Keep generated translated audio available for replay and explicit sharing, subject to the user's retention choice.
- [ ] Add abuse prevention for voice cloning, including account controls, consent records, rate limits, audit events, and provider policy enforcement.

## Authentication, privacy, and security

- [ ] Use short-lived access tokens with refresh-token rotation and secure platform storage such as Android Keystore and iOS Keychain.
- [ ] Encrypt all remote transport with modern TLS; use certificate validation and consider certificate pinning only with a safe rotation strategy.
- [ ] Require explicit consent before microphone access, remote audio transmission, voice-profile enrollment, cloud retention, or sharing.
- [ ] Show a persistent connection/processing indicator when audio is being sent to a remote service.
- [ ] Provide a per-session remote-processing disclosure that identifies the server region or self-hosted endpoint when available.
- [ ] Define retention defaults for raw audio, transcripts, translated text, generated audio, voice references, logs, and crash reports.
- [ ] Make deletion requests verifiable and propagate them to object storage, caches, worker scratch space, backups where applicable, and derived voice-profile artifacts.
- [ ] Avoid putting raw audio, transcripts, tokens, or voice references in ordinary application logs or analytics events.
- [ ] Add tenant isolation, authorization checks, abuse monitoring, request quotas, and replay protection on the inference service.
- [ ] Document the privacy difference between managed cloud inference and self-hosted remote inference.
- [ ] Record model-license and distribution boundaries in server metadata and surface relevant restrictions before a model is used.

## Capability negotiation and future local inference

- [ ] Define a capability manifest exchanged during sign-in and session setup, including supported local models, remote models, languages, codecs, cloning support, device memory, accelerator type, and battery constraints.
- [ ] Let the server and client select a processing plan per function: local VAD, local ASR, remote translation, remote TTS, or fully local execution.
- [ ] Keep each pipeline stage independently replaceable so local and remote stages can be mixed without changing the user-facing workflow.
- [ ] Add a policy setting for `remote_only`, `hybrid`, and `local_preferred` processing, with a clear explanation of privacy, latency, battery, and quality tradeoffs.
- [ ] Never move a stage from remote to local without showing the user what changed and which model/package will be installed.
- [ ] Verify model licenses, package sizes, RAM/VRAM requirements, thermal behavior, and battery impact before enabling local mobile inference.
- [ ] Support downloadable model bundles with integrity checks, resumable downloads, version pinning, rollback, and storage management.
- [ ] Use hardware acceleration where supported, including Android GPU/NPU delegates and iPhone Neural Engine/Core ML paths, while retaining a CPU fallback where practical.
- [ ] Add thermal and battery safeguards that pause, downgrade, or move inference remote when the device cannot sustain local execution.
- [ ] Define an upgrade path where the same account, voice profiles, settings, and workflow can move between remote, hybrid, and fully local execution.
- [ ] Keep local-only mode functional without network access once all required models and assets are installed.

## Mobile UX and workflows

- [ ] Provide a clear home screen for starting a live session, creating a fixed translated clip, managing voice profiles, and selecting a remote endpoint.
- [ ] Show source captions, target captions, translated audio state, connection quality, inference location, and latency without overwhelming the live conversation view.
- [ ] Provide a compact live-session control for pause, mute, stop, target language, voice profile, processing mode, and output route.
- [ ] Make remote connection loss recoverable without losing the user's current language and voice selections.
- [ ] Show a meaningful offline state and offer local-only capabilities when available rather than displaying a generic failure.
- [ ] Include a test bench for microphone checks, speaker checks, network latency, remote worker availability, and a short translation/TTS test.
- [ ] Provide a share/export flow for translated audio clips, captions, transcripts, and provenance metadata.
- [ ] Support Dynamic Type, screen readers, high contrast, reduced motion, large touch targets, and one-handed use.
- [ ] Avoid implying that a remote model is installed on the phone when it is only available through the connected service.

## Operations and deployment

- [ ] Define infrastructure-as-code for the gateway, authentication, queue, object storage, metrics, logs, secrets, and GPU worker pool.
- [ ] Support separate development, staging, and production inference environments with model allowlists.
- [ ] Add health checks for worker readiness, model loading, CUDA/runtime compatibility, storage, queue depth, and network reachability.
- [ ] Track GPU utilization, VRAM, CPU, RAM, queue delay, inference latency, audio duration, failure rate, and disconnect rate without collecting unnecessary user content.
- [ ] Add cost controls: per-user quotas, maximum clip duration, concurrency limits, idle worker shutdown, and configurable model residency.
- [ ] Support regional deployment and data-residency configuration where required.
- [ ] Add model rollout, canary, rollback, and compatibility checks before changing a production worker model.
- [ ] Provide an administrator and self-hosting guide for configuring GPU hardware, model storage, certificates, firewall rules, and retention policies.

## Testing and acceptance criteria

- [ ] Test Android and iPhone audio capture/playback across current and older supported OS versions and representative hardware.
- [ ] Test interruptions from calls, notifications, Bluetooth changes, screen lock, backgrounding, permissions revocation, and battery-saving modes.
- [ ] Test remote streaming under latency, jitter, loss, reconnection, server restart, worker replacement, and partial-service failure.
- [ ] Test language pairs, code-switching, silence, overlapping speakers, long utterances, short clauses, accents, and pronunciation edge cases.
- [ ] Measure first-audio latency, steady-state latency, caption accuracy, translation quality, voice similarity, intelligibility, battery drain, thermal rise, and data usage.
- [ ] Verify that no raw audio is retained unless the user explicitly requested recording or voice enrollment.
- [ ] Verify that generated clips include accurate language, voice, processing-location, and model metadata.
- [ ] Verify remote-only mode works without shipping model weights in the mobile package.
- [ ] Verify hybrid mode routes only the intended stages locally and remotely.
- [ ] Verify fully local mode can operate without network access when its required models are installed.
- [ ] Add contract tests ensuring Android, iPhone, desktop, and self-hosted clients remain compatible with supported protocol versions.

## Delivery phases

- [ ] Phase 1: finalize session protocol, authentication, privacy contract, and a minimal remote inference gateway.
- [ ] Phase 2: build a remote-only Android proof of concept with live captions and translated audio.
- [ ] Phase 3: build the equivalent iPhone proof of concept with native audio routing and interruption handling.
- [ ] Phase 4: add voice profiles, cloned TTS, fixed clips, downloads, sharing, and user-configurable speech timing.
- [ ] Phase 5: add self-hosted remote-server support and deployment documentation.
- [ ] Phase 6: add capability negotiation and selected hybrid local stages such as VAD or lightweight ASR.
- [ ] Phase 7: benchmark and selectively ship fully local models on supported phones without changing the core workflow.
- [ ] Phase 8: maintain remote, hybrid, and local execution as explicit supported modes rather than silently changing processing location.
