# XTTS Romanian Low-VRAM Cloning Plan

Status: In progress

Purpose: Add a low-VRAM Romanian/English cloned-voice TTS path built around `eduardem/xtts-v2-romanian-v2`, with true streaming, cached speaker conditioning, Romanian Unicode normalization, and an optional target-language conditioning bridge for cases where an English reference does not preserve identity well when synthesizing Romanian.

## Model and runtime integration

- [ ] Add `eduardem/xtts-v2-romanian-v2` to the built-in TTS catalog with accurate Romanian/English, streaming, cloning, licensing, and RTX 2070-oriented VRAM metadata.
- [ ] Add an `XttsRomanianTtsAdapter` using the low-level XTTS API rather than the high-level blocking `TTS.api.TTS` wrapper.
- [ ] Load the local downloaded checkpoint when available and fail clearly when the XTTS runtime or required model files are missing.
- [ ] Keep the model lazy/explicitly unloadable so it can participate in VoxPassport model hot-swap and low-VRAM residency policy.
- [ ] Wire XTTS into TTS model normalization, activation, runtime adapter selection, and adapter exports.

## Romanian text correctness

- [ ] Normalize legacy Romanian cedilla characters (`ş`, `ţ`, `Ş`, `Ţ`) to comma-below (`ș`, `ț`, `Ș`, `Ț`) before XTTS tokenization.
- [ ] Raise the Romanian tokenizer character limit to 250 when the tokenizer exposes `char_limits`.
- [ ] Bound generated audio-token length dynamically from the input word count to mitigate the Romanian fine-tune stop-token issue.
- [ ] Keep live utterances clause-sized rather than feeding long paragraphs into one autoregressive generation.

## Streaming and low-VRAM behavior

- [ ] Use XTTS `inference_stream()` and emit PCM chunks as they become available; do not synthesize a complete WAV and fake streaming afterward.
- [ ] Use FP16 on CUDA and inference mode/no-grad execution.
- [ ] Serialize heavy XTTS GPU execution through the existing VoxPassport GPU inference coordinator.
- [ ] Avoid retaining arbitrary per-request CUDA tensors after synthesis.
- [ ] Add a bounded conditioning cache so repeated use of the same voice profile does not recompute speaker latents every utterance.
- [ ] Clear conditioning tensors and CUDA allocator cache on adapter unload.

## Cross-lingual voice-conditioning workaround

- [ ] Support an optional per-profile target-language reference file for Romanian conditioning without replacing the canonical real voice recording.
- [ ] Derive the final XTTS profile from a real speaker embedding plus an optional Romanian GPT conditioning latent when both references are available.
- [ ] Fall back to ordinary single-reference XTTS conditioning when no target-language reference exists.
- [ ] Keep synthetic/derived target-language references separate from canonical voice identity files and make the file naming explicit.
- [ ] Do not add model training/fine-tuning to the live path; teacher-generated Romanian reference creation remains an offline enrollment step.

## Validation and soak testing

- [ ] Add unit tests for Romanian cedilla normalization.
- [ ] Add tests proving target-language reference selection does not replace the canonical speaker reference.
- [ ] Add tests proving conditioning-cache keys change when either reference changes.
- [ ] Add tests for dynamic token limits and bounded Romanian text handling.
- [ ] Add an XTTS-specific soak harness/configuration for 50+ alternating English/Romanian cloned turns and CUDA-memory tracking when hardware/runtime are present.
- [ ] Preserve existing tests and avoid requiring model downloads for unit-test collection.

## Documentation and acceptance

- [ ] Document the two conditioning modes: ordinary zero-shot cloning and real-speaker-embedding + Romanian-conditioning bridge.
- [ ] Document that the bridge reference may be generated offline by a heavier model such as MOSS, but MOSS is not required or resident during live XTTS inference.
- [ ] Document the required Romanian Unicode normalization and the Romanian model's stop-token limitation.
- [ ] Mark this plan complete only after code, tests, catalog metadata, and documentation are all committed consistently.
