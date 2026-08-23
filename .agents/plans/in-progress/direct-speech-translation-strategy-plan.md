# Cascade vs Direct Speech Translation Strategy Plan

Status: In progress

Purpose: Make speech translation strategy a first-class, provider-neutral runtime choice. Preserve the existing modular `VAD -> ASR -> NMT -> TTS` path while supporting direct streaming speech translation providers that may emit translated text, translated audio, or both. Communication transport (desktop virtual audio, browser integration, future mobile calling) remains independent from inference strategy.

## Architectural definition

- [x] Add `DIRECT_SPEECH_TRANSLATION` as a distinct model/runtime capability.
- [x] Add a manifest/catalog layer for direct speech providers and execution modes.
- [x] Define provider-neutral streaming session configuration and event contracts in `runtime/inference/translation_session.py`.
- [x] Permit direct strategies to emit source captions, translated captions, translated audio, state, and errors.
- [x] Keep communication transport outside the translation-strategy contract.
- [x] Do not force true audio-to-audio providers through ASR, NMT, or TTS abstractions.
- [ ] Add a persisted `pipeline_strategy` with at least `cascade_asr_nmt` and `direct_speech_translation`.
- [ ] Define an executable cascade strategy adapter behind the same session contract.
- [ ] Define an executable direct-provider strategy adapter behind the same session contract.
- [ ] Keep VAD/endpointing policy explicit per strategy rather than assuming every remote provider requires local VAD.
- [ ] Keep optional diarization independent from strategy and off the blocking critical path.

## Provider metadata

- [x] Distinguish execution modes: local, BYO API, self-hosted/private, and managed cloud.
- [x] Expose provider transport, authentication kind, language discovery, streaming, bidirectionality, voice-preservation capability, and lifecycle.
- [x] Register Gemini 3.5 Live Translate declaratively as a BYO-API preview provider.
- [ ] Expose provider catalog through a stable runtime API for the Expo client.
- [ ] Keep credentials out of provider manifests and ordinary UI state/logging.
- [ ] Define secure BYO-key storage/hand-off for native and web targets.

## Session behavior

- [x] Define `SpeechTranslationSessionConfig` with language pair, audio format, output mode, optional source transcript, and optional voice profile ID.
- [x] Define ordered text/audio/state/error events.
- [x] Validate malformed session/event/audio contracts at construction time.
- [ ] Define session flow control/backpressure and maximum buffered audio.
- [ ] Define provider reconnect/resume behavior where supported.
- [ ] Define interruption/barge-in semantics.
- [ ] Define whether voice preservation comes from the direct provider or VoxPassport TTS/voice-profile pipeline.
- [ ] Never silently substitute stock TTS for requested voice preservation.

## Strategy state and mutual exclusion

- [ ] Promote direct speech translation from catalog metadata to a real active runtime strategy.
- [ ] Persist the active strategy and selected direct provider.
- [ ] Preserve the user's last cascade ASR/NMT/TTS selections while direct mode is active.
- [ ] Make strategy transitions transactional: validate -> load/connect -> health/language check -> route switch -> retire superseded heavy resources.
- [ ] Roll back to the prior known-good strategy if activation fails.
- [ ] Do not uninstall or forget inactive models.
- [ ] Show configured/inactive versus loaded/resident state explicitly.

## Expo client

- [ ] Present **Translation Engine** as a strategy choice rather than mixing Gemini into TTS/NMT model lists.
- [ ] Show modular local pipeline, direct providers, and private/self-hosted strategies using backend-owned metadata.
- [ ] Show execution mode and authentication requirement.
- [ ] Show whether source captions, translated captions, translated audio, and voice preservation are available.
- [ ] Disable providers whose executable adapter is not implemented or whose language pair is unsupported.
- [ ] Do not hard-code Gemini/Google branches into generic Expo components.

## Gemini Live Translate provider

- [ ] Implement a Gemini Live Translate session adapter behind `SpeechTranslationStrategyAdapter`.
- [ ] Keep Google authentication/provider-specific WebSocket messages inside the provider adapter.
- [ ] Support English <-> Romanian only after runtime/provider capability verification.
- [ ] Map provider transcripts/audio/state/errors into VoxPassport session events.
- [ ] Define provider-side sample-rate/codec conversion ownership.
- [ ] Handle preview-model lifecycle/errors explicitly.
- [ ] Record latency/usage metadata without exposing API secrets.

## Local direct-model candidates

- [ ] Re-evaluate Canary/Seamless only as local direct-model candidates; do not make them architectural assumptions.
- [ ] Do not call endpoint-only inference streaming without evidence.
- [ ] Benchmark both directions independently.
- [ ] Keep experimental candidates disabled until their real adapter is healthy.

## Resource policy

- [ ] Measure strategy VRAM/RAM/latency instead of assuming direct is cheaper.
- [ ] Compare against the actual RTX 2070 cascade policy.
- [ ] Account for direct provider/local-model resources and any separate TTS required by the selected output mode.
- [ ] Preserve heavyweight GPU serialization where concurrent local stages exceed the memory budget.
- [ ] Add bounded degraded/failure behavior rather than unbounded audio queues.

## Testing and acceptance

- [x] Add unit tests for streaming session configuration and event invariants.
- [x] Add provider catalog tests.
- [ ] Add fake strategy/session integration tests for ordering, close, failures, and backpressure.
- [ ] Add strategy persistence/mutual-exclusion tests.
- [ ] Add transition rollback/failure-injection tests.
- [ ] Add Gemini adapter tests using recorded/mock protocol messages without requiring a live API key in CI.
- [ ] Add English/Romanian end-to-end tests for cascade and at least one real direct provider.
- [ ] Do not mark complete until a direct adapter produces real translated output and strategy switching is transactional.
