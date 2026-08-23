# Cascade vs Direct Speech Translation Strategy Plan

Status: Planned for a future implementation agent

Purpose: Add a mutually exclusive pipeline strategy that lets the user choose the existing ASR-plus-NMT cascade or a direct speech-translation model, with a T-chart presentation in Model Settings and transactional backend switching.

## Architectural definition

- [ ] Add a persisted `pipeline_strategy` enum with at least:
  - [ ] `cascade_asr_nmt`
  - [ ] `direct_speech_translation`
- [ ] Define the cascade path as `Speech -> VAD/endpointing -> ASR -> NMT -> translated text`.
- [ ] Define the direct path as `Speech -> VAD/endpointing -> Direct Speech Translation -> translated text`.
- [ ] Keep TTS/voice cloning after either text-producing strategy.
- [ ] Keep VAD active for endpointing under both strategies.
- [ ] Keep optional diarization independent from the strategy and off the blocking critical path.
- [ ] Do not claim that a direct text-output model replaces cloned TTS.

## Model Settings T-chart

- [ ] Add a horizontal separator labeled **Speech Translation Strategy**.
- [ ] Add a two-column T-chart with a visible vertical separator.
- [ ] Label the left column **Cascade: ASR + Translation**.
- [ ] Stack the ASR model section and NMT model section in the left column.
- [ ] Label the right column **Direct Speech Translation**.
- [ ] Show compatible direct-model cards in the right column.
- [ ] Add a second horizontal separator below the T-chart.
- [ ] Place TTS/Voice Cloning, VAD, and optional Diarization below the second separator as independent model types.
- [ ] Show a concise flow diagram and resource summary for each side.
- [ ] Mark the cascade as the recommended RTX 2070 strategy until direct candidates win local benchmarks.
- [ ] Mark nonfunctional adapters as **Adapter not implemented** and disable activation.

## Mutual-exclusion behavior

- [ ] Selecting a direct model must deactivate the ASR and NMT runtime slots before direct inference starts.
- [ ] Preserve the user's most recent ASR and NMT selections as the inactive cascade configuration.
- [ ] Dim and disable cascade activation controls while the direct strategy is active.
- [ ] Selecting either cascade column or a cascade model must deactivate and unload the direct model.
- [ ] Restore the remembered ASR and NMT selections when returning to cascade mode.
- [ ] Do not uninstall, delete, or forget models merely because their strategy is inactive.
- [ ] Show which models are configured but inactive versus loaded and resident.

## Backend slot and state work

- [ ] Promote `DIRECT_SPEECH_TRANSLATION` from catalog-only capability to a real runtime slot.
- [ ] Extend active-slot persistence to include direct speech translation and pipeline strategy.
- [ ] Add strategy state to `/api/status`.
- [ ] Add an API to validate a proposed strategy transition before mutating runtime state.
- [ ] Make strategy activation transactional:
  - [ ] Pause new inference work
  - [ ] Drain or safely cancel current utterances
  - [ ] Load the candidate adapter
  - [ ] Run health and language-pair checks
  - [ ] Switch routing atomically
  - [ ] Unload superseded heavy models
  - [ ] Resume capture and processing
- [ ] Roll back to the previous last-known-good strategy if any transition stage fails.
- [ ] Keep audio capture buffering bounded during the transition.
- [ ] Broadcast strategy changes and failures to captions/status clients.

## Direct adapter contract

- [ ] Replace the current Canary stub with a real buffered/streaming adapter before enabling its card.
- [ ] Define endpoint-level input and partial/final translated-text events.
- [ ] Include source language, target language, timestamps, confidence where available, and model metadata.
- [ ] Define whether a direct adapter can also return a source transcript from the same encoder pass.
- [ ] If source transcription requires a second decode, expose that latency and memory cost honestly.
- [ ] Preserve source captions, translated captions, phrase boundaries, context, and metrics where the selected model supports them.
- [ ] Specify fallback behavior when the direct model does not support the selected language pair.
- [ ] Reject a strategy that cannot produce requirements needed by the current conference mode.

## Initial candidates

- [ ] Implement and benchmark NVIDIA Canary-1B-v2 first for direct speech-to-translated-text.
- [ ] Verify English-to-Romanian and Romanian-to-English independently.
- [ ] Confirm the installed NeMo version and Windows/CUDA compatibility before advertising support.
- [ ] Evaluate partial-result or chunked behavior; do not call an endpoint-only model streaming without evidence.
- [ ] Keep Canary classified as experimental until it beats or acceptably approaches the cascade in quality and conversational latency.
- [ ] Evaluate Meta SeamlessM4T/SeamlessStreaming as a separate candidate, not as an assumed drop-in replacement.
- [ ] Account for Seamless runtime dependencies, checkpoint size, vocoder requirements, and Windows support.
- [ ] Do not route Seamless speech output around the active cloned TTS unless the user explicitly selects non-cloned direct speech output.

## Resource policy

- [ ] Measure direct-strategy VRAM rather than assuming that one model uses less memory than two model types.
- [ ] Compare against the actual RTX 2070 cascade policy, where Parakeet uses GPU and MiLMMT is CPU-offloaded.
- [ ] Track steady GPU memory, peak GPU memory, CPU RAM, load time, and real-time factor.
- [ ] Include TTS residency and generation peak in the full-pipeline comparison.
- [ ] Preserve the heavyweight GPU inference coordinator if direct translation and Higgs cannot safely overlap.
- [ ] Add strategy-specific degraded modes for queue growth, VRAM pressure, and inference failure.
- [ ] Do not activate optional GPU sidecars when the strategy's measured memory budget leaves insufficient headroom.

## Quality and behavior benchmarks

- [ ] Create a repeatable English/Romanian conversational benchmark set with consented or synthetic audio.
- [ ] Compare source transcription accuracy where applicable.
- [ ] Compare translated-text quality using semantic and human review, not token overlap alone.
- [ ] Measure endpoint-to-first-translation and endpoint-to-final-translation latency.
- [ ] Measure capture-to-first-cloned-audio latency with Higgs included.
- [ ] Test interruptions, overlapping speakers, long utterances, short clauses, silence, and code-switching.
- [ ] Test whether direct translation preserves enough source information for source captions and debugging.
- [ ] Save benchmark results with exact model/runtime/hardware revisions.

## UI status and safety

- [ ] Show the active strategy in Live, Test Bench, Workflow, and `/api/status`.
- [ ] Show a loading/transition state instead of briefly displaying both strategies as active.
- [ ] Explain disabled cards with a tooltip or inline reason.
- [ ] Warn when selecting a direct strategy removes source-caption capability or increases estimated VRAM.
- [ ] Never silently fall back from direct to cascade or from cloned TTS to a stock voice.
- [ ] Offer explicit rollback to the previous strategy after a failed benchmark or activation.

## Testing and acceptance criteria

- [ ] Add unit tests for strategy persistence and remembered inactive selections.
- [ ] Add integration tests proving mutual exclusivity of direct versus ASR/NMT runtime slots.
- [ ] Add failure-injection tests for load, health-check, language, and unload failures.
- [ ] Add tests proving rollback restores the previous working cascade.
- [ ] Add tests proving TTS, VAD, and diarization are not incorrectly disabled by strategy switching.
- [ ] Add UI tests for the two horizontal separators, vertical separator, column state, and accessibility.
- [ ] Add end-to-end tests for both English-to-Romanian and Romanian-to-English paths.
- [ ] Do not mark the work complete until a direct adapter produces real translated text and no stub can report healthy.
- [ ] Update README architecture and low-VRAM guidance after implementation.
