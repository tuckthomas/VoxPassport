# Voice Conversion Capability Plan

Status: Staging — planning only; no implementation work authorized by this document.

Purpose: Add a provider-neutral, low-latency voice-conversion capability to VoxPassport without replacing the existing cloned-TTS path. Voice conversion should support standalone real-time voice transformation and optional post-processing of translated audio produced by direct speech-translation providers or non-cloning TTS engines.

## Architectural intent

- [ ] Add `VOICE_CONVERSION` as a distinct model/runtime capability.
- [ ] Keep voice conversion separate from `TTS`, `DIRECT_SPEECH_TRANSLATION`, `ASR`, and `TRANSLATION` abstractions.
- [ ] Do not route ordinary cloning-capable TTS through voice conversion by default.
- [ ] Preserve the existing `TTS_CLONED` path as the preferred direct text-to-cloned-speech path when its quality and latency are acceptable.
- [ ] Treat voice conversion as an optional stage that can consume already-generated PCM audio.
- [ ] Keep communication transport and audio routing independent from voice-conversion provider selection.
- [ ] Keep application business logic free of provider/model-name branches.

## Primary use cases

- [ ] Support standalone live voice conversion: physical microphone -> voice conversion -> virtual microphone.
- [ ] Support translated-audio voice preservation: direct translated audio -> optional voice conversion -> configured output bus.
- [ ] Support generic/non-cloning TTS post-processing: TTS audio -> optional voice conversion -> configured output bus.
- [ ] Allow voice conversion to be disabled independently for inbound and outbound translation directions.
- [ ] Do not require ASR, translation, or TTS for standalone voice-conversion mode.
- [ ] Do not force direct speech-to-speech providers through ASR/NMT/TTS merely to apply a saved speaker identity.

## Voice-profile integration

- [ ] Reuse the existing engine-independent VoxPassport voice profile as the canonical speaker identity source.
- [ ] Never replace or overwrite `reference.wav` with provider-specific derived assets.
- [ ] Permit providers to derive and cache model-specific conditioning from the canonical profile.
- [ ] Store provider-specific voice-conversion assets under a dedicated profile subtree such as `vc/<provider>/`.
- [ ] Keep provider-specific embeddings, feature tensors, adapters, or compiled profile assets replaceable and reproducible from canonical source material when practical.
- [ ] Preserve optional transcripts and target-language conditioning files already used by TTS providers.
- [ ] Define invalidation rules so derived voice-conversion assets are rebuilt when canonical reference material changes.
- [ ] Allow one saved voice profile to serve TTS cloning and voice-conversion providers without duplicating the user-facing profile.

## Provider-neutral runtime contract

- [ ] Define a `VoiceConversionProvider` or equivalent provider-neutral runtime interface.
- [ ] Define provider lifecycle operations for load, unload, health, and diagnostics.
- [ ] Define profile preparation/loading semantics independently from live audio streaming.
- [ ] Define a streaming PCM input/output contract with explicit sample rate, channel count, and sample format.
- [ ] Define bounded audio queues and backpressure.
- [ ] Define stream start, chunk conversion, flush, interruption, and stop semantics.
- [ ] Define whether a provider supports zero-shot conversion, personalized adaptation, cross-lingual conversion, CPU inference, CUDA inference, and true streaming.
- [ ] Define provider-reported algorithmic latency, preferred chunk size, lookahead, and sample-rate requirements.
- [ ] Keep provider/model-specific preprocessing behind the provider boundary.

## Model manifests and runtime supervision

- [ ] Add voice-conversion manifests or equivalent registry metadata rather than hard-coding providers in the daemon or UI.
- [ ] Reuse the existing runtime-profile concept for dependency-compatible voice-conversion families.
- [ ] Add a dedicated supervisor only if the existing process-supervision primitives cannot be cleanly generalized.
- [ ] Ensure local voice-conversion processes use supervisor-owned lifecycle and health management.
- [ ] Avoid unmanaged localhost GPU processes.
- [ ] Use dynamic local endpoints when a provider requires a worker/server process.
- [ ] Support explicit non-loopback remote providers without treating them as local GPU residency.
- [ ] Make activation transactional: validate -> load -> health/profile check -> commit active state.
- [ ] Roll back to the prior known-good provider when activation fails before routing changes are committed.
- [ ] Make provider release reclaim model/runtime resources deterministically.

## GPU and resource policy

- [ ] Measure actual VRAM, RAM, CPU, and latency instead of assuming voice conversion is lightweight.
- [ ] Preserve the current constrained-GPU policy on 8 GB-class systems.
- [ ] Coordinate local voice-conversion inference with heavyweight ASR/TTS execution when concurrent CUDA residency is unsafe.
- [ ] Determine whether selected voice-conversion providers can remain resident alongside the active ASR and/or TTS model.
- [ ] Support CPU placement where latency remains acceptable and doing so preserves GPU headroom.
- [ ] Expose allocated/reserved GPU memory and provider residency in runtime diagnostics.
- [ ] Define deterministic unload behavior for provider switches and translation-strategy changes.

## Standalone live voice-conversion mode

- [ ] Add a standalone operating mode that bypasses ASR, translation, and TTS.
- [ ] Route `BUS_PHYSICAL_MIC` into the active voice-conversion provider.
- [ ] Route converted PCM to `BUS_VIRTUAL_MIC` or another explicitly selected output.
- [ ] Preserve existing feedback/echo-isolation rules so converted output is not recaptured as fresh microphone input.
- [ ] Support start/stop and provider/profile selection without restarting the main VoxPassport runtime.
- [ ] Define passthrough behavior when conversion is disabled or unavailable.
- [ ] Do not silently substitute a different profile or provider after a conversion failure.

## Direct speech-translation integration

- [ ] Extend direct-speech session metadata to indicate whether translated audio may be post-processed by VoxPassport voice conversion.
- [ ] Keep provider-native voice preservation distinct from VoxPassport-applied voice conversion.
- [ ] If a direct provider already preserves the requested speaker adequately, allow conversion to remain disabled.
- [ ] If a direct provider emits a generic or incorrect speaker identity, allow translated PCM to pass through the selected voice-conversion provider before routing.
- [ ] Preserve provider translated-text and caption events independently from converted audio.
- [ ] Define interruption/barge-in behavior so stale converted audio is dropped promptly.
- [ ] Account for the voice-conversion stage in end-to-end direct-speech latency metrics.

## Modular cascade integration

- [ ] Keep the default cascade as VAD -> ASR -> translation -> selected TTS.
- [ ] Preserve direct cloned TTS as the normal path when the active TTS supports acceptable cross-lingual cloning.
- [ ] Allow optional `TTS -> voice conversion` only when explicitly selected or when benchmarking demonstrates a material advantage.
- [ ] Do not assume generic TTS plus voice conversion is faster than a cloning-capable TTS.
- [ ] Preserve current TTS voice-profile conditioning behavior and target-language conditioning workarounds.
- [ ] Prevent double speaker conditioning when a cloned-TTS output is already sufficiently close to the requested identity.

## Initial provider evaluation

- [ ] Evaluate currently available streaming zero-shot voice-conversion projects for Windows compatibility, licensing, model availability, and local deployment.
- [ ] Prefer providers with released code/checkpoints, true streaming inference, cross-lingual evidence, and practical 8 GB GPU requirements.
- [ ] Treat unreleased research implementations as watchlist entries rather than implementation dependencies.
- [ ] Record whether each candidate supports speaker-reference caching or requires reference features during every stream.
- [ ] Record whether each candidate supports optional speaker-specific fine-tuning/adaptation.
- [ ] Keep model/provider selection declarative so a better future model can replace the initial candidate without application-level rewrites.

## Benchmark plan

- [ ] Add a repeatable English <-> Romanian voice-conversion benchmark corpus.
- [ ] Measure microphone-to-output latency for standalone conversion.
- [ ] Measure algorithmic latency separately from audio-device/buffer latency.
- [ ] Measure real-time factor and time to first converted audio.
- [ ] Measure peak allocated/reserved VRAM and steady-state RAM.
- [ ] Measure speaker similarity using the same reference profile across providers.
- [ ] Evaluate Romanian pronunciation/articulation after converting native-quality Romanian source speech into an English-enrolled target voice.
- [ ] Evaluate English identity preservation independently from Romanian cross-lingual preservation.
- [ ] Test stability across short phrases, long utterances, pauses, interruptions, and rapid speaker starts/stops.
- [ ] Compare direct cloned-TTS against generic TTS plus voice conversion on identical translated text.
- [ ] Compare direct speech-translation audio with and without voice-conversion post-processing.
- [ ] Record added latency from the conversion stage rather than reporting only model inference time.

## Required comparison paths

- [ ] Benchmark OmniVoice direct cloning -> output.
- [ ] Benchmark XTTS Romanian direct cloning -> output.
- [ ] Benchmark the best current generic/stock Romanian TTS -> voice conversion -> output.
- [ ] Benchmark direct translated audio -> voice conversion -> output when a direct provider is available.
- [ ] Benchmark physical microphone -> voice conversion -> virtual microphone.
- [ ] Do not promote generic TTS plus voice conversion over direct cloned TTS unless measurements show a concrete latency, quality, resource, or portability advantage.

## Quality and failure policy

- [ ] Define minimum speaker-similarity and intelligibility thresholds before enabling a provider as recommended.
- [ ] Reject configurations that materially damage target-language pronunciation even if speaker similarity improves.
- [ ] Surface provider/profile incompatibility explicitly.
- [ ] Avoid unbounded buffering when conversion falls behind real time.
- [ ] Drop stale audio rather than allowing latency to grow indefinitely in live conversation.
- [ ] Define pre-audio retry behavior separately from partial-audio failures.
- [ ] Never replay partially emitted converted speech automatically after a provider crash.

## Client/UI work

- [ ] Add Voice Conversion as its own capability/engine section rather than presenting it as another TTS model.
- [ ] Add a standalone Voice Conversion mode to the canonical Expo client.
- [ ] Allow selection of active voice profile and conversion provider.
- [ ] Expose live latency, device routing, provider health, and residency state.
- [ ] Show whether the selected provider supports cross-lingual conversion and personalized adaptation.
- [ ] Allow direct-speech translation sessions to opt into VoxPassport voice preservation when supported.
- [ ] Do not hard-code provider-specific controls in generic screens unless exposed through provider capability metadata.

## Diagnostics and observability

- [ ] Add voice-conversion provider/model/profile state to runtime diagnostics.
- [ ] Report stream state, chunk size, queue depth, underruns/overruns, and measured conversion latency.
- [ ] Report active input/output sample rates and resampling stages.
- [ ] Report CPU/GPU execution placement.
- [ ] Report profile-preparation/cache state without exposing raw private voice material unnecessarily.
- [ ] Add structured errors for provider load failure, profile failure, incompatible audio format, device failure, and realtime overrun.

## Testing

- [ ] Add provider-contract unit tests using fake PCM providers.
- [ ] Add lifecycle tests for load, profile preparation, stream start/stop, unload, and crash recovery.
- [ ] Add bounded-queue/backpressure tests.
- [ ] Add audio-routing tests proving converted output cannot feed back into source capture.
- [ ] Add strategy tests proving ordinary cloned TTS does not gain an implicit conversion stage.
- [ ] Add direct-speech tests proving translated audio can optionally pass through conversion without changing caption/text events.
- [ ] Add profile invalidation tests for changed canonical reference audio.
- [ ] Add runtime-profile/dependency-isolation tests for providers requiring incompatible environments.
- [ ] Add failure-injection tests for provider crashes before and after partial audio emission.
- [ ] Add Windows hardware acceptance testing with the VoxPassport virtual microphone.

## Documentation and acceptance

- [ ] Document voice conversion as a separate capability from TTS cloning.
- [ ] Document the standalone live-conversion signal path.
- [ ] Document the optional direct-speech translated-audio post-processing path.
- [ ] Document why direct cloning-capable TTS remains the default cascade path unless benchmarks justify otherwise.
- [ ] Document voice-profile derived-asset ownership and invalidation rules.
- [ ] Record current-hardware benchmark results before recommending a default provider.
- [ ] Move this plan from `staging` to `in-progress` only after implementation is explicitly authorized.
- [ ] Do not mark complete until at least one real provider has passed standalone, cross-lingual, resource, routing, and failure-recovery acceptance tests.
