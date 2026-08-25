# Cascade vs Direct Speech Translation Strategy Plan

Status: Core implementation complete; additional providers and live-provider/hardware benchmarking are deferred follow-on work

Purpose: Make speech translation strategy a first-class, provider-neutral runtime choice while preserving the modular `VAD -> ASR -> NMT -> TTS` path and supporting direct streaming speech translation providers. Communication transport remains independent from inference strategy.

## Completed architecture

- [x] Add `DIRECT_SPEECH_TRANSLATION` as a distinct runtime capability.
- [x] Add provider/strategy manifests and execution-mode metadata.
- [x] Define provider-neutral streaming session configuration and ordered text/audio/state/error events.
- [x] Keep communication-platform transport outside the translation-strategy contract.
- [x] Keep true audio-to-audio providers outside forced ASR/NMT/TTS decomposition.
- [x] Implement bounded session/event queues and backpressure.
- [x] Keep provider credentials out of manifests and ordinary client state/logging.
- [x] Persist/restore selected strategy state safely.
- [x] Preserve modular model selections while direct mode is active.
- [x] Make strategy activation transactional with candidate validation and rollback.
- [x] Block strategy/routing mutation while a live native session owns the media path.
- [x] Keep optional diarization independent from the blocking critical path.

## Expo/client ownership

- [x] Present translation strategy separately from TTS/NMT model selection.
- [x] Drive provider/strategy presentation through backend-owned metadata and typed APIs.
- [x] Expose execution mode/authentication/capability state without hard-coding Google/Gemini branches into generic Expo components.
- [x] Keep high-frequency PCM on runtime/native media paths rather than React state or REST JSON.

## Gemini Live Translate

- [x] Register Gemini Live Translate declaratively as a BYO-API direct strategy.
- [x] Implement the provider adapter behind the provider-neutral session contract.
- [x] Keep Google authentication and provider wire messages inside the adapter.
- [x] Map provider transcripts, translated audio, interruption, state, errors and `goAway` behavior into VoxPassport events.
- [x] Keep sample-rate/codec conversion ownership outside generic Expo components.
- [x] Prevent API-key leakage through provider connection exceptions.

## Testing completed

- [x] Session configuration/event invariant tests.
- [x] Provider catalog/loader tests.
- [x] Fake session integration tests for ordering, close/failure and bounded queues.
- [x] Strategy persistence, mutual-exclusion and transactional rollback/failure-injection tests.
- [x] Gemini wire-protocol tests using mock/recorded protocol behavior rather than a live CI key.
- [x] Runtime Integrity coverage for provider catalog, loader, session, Gemini adapter and strategy manager.

## Deferred follow-on work

These are intentionally not blockers for the completed strategy architecture:

- [ ] Add additional direct-speech providers through the same manifest/adapter/session contract.
- [ ] Run live English/Romanian provider acceptance with real credentials/network conditions and record end-to-end quality/latency.
- [ ] Re-evaluate local/open direct-speech model candidates with measured streaming behavior rather than architectural assumptions.
- [ ] Compare direct-provider cost/latency/quality/resource behavior against the actual local RTX 2070 cascade.
- [ ] Extend voice-preservation benchmarking for providers that advertise native voice preservation.

## Completion decision

The core goal of this plan is complete: direct speech translation is now an executable, provider-neutral peer to the modular cascade, with persisted transactional strategy switching, bounded media/event behavior, a real Gemini adapter, and CI tests. Future provider additions and live service benchmarking are feature/acceptance follow-ons and are tracked by the broader platform plan rather than keeping this architecture plan open.
