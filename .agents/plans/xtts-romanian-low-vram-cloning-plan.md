# XTTS Romanian Low-VRAM Cloning Plan

Status: Implementation complete; RTX 2070 acceptance testing pending

Purpose: Add a low-VRAM Romanian/English cloned-voice TTS path built around `eduardem/xtts-v2-romanian-v2`, with true streaming, cached speaker conditioning, Romanian Unicode normalization, and an optional target-language conditioning bridge for cases where an English reference does not preserve identity well when synthesizing Romanian.

## Model and runtime integration

- [x] Add `eduardem/xtts-v2-romanian-v2` to the built-in TTS catalog with Romanian/English, streaming, cloning, licensing, and RTX 2070-oriented planning metadata.
- [x] Add an `XttsRomanianTtsAdapter` backed by the low-level XTTS API rather than the high-level blocking `TTS.api.TTS` wrapper.
- [x] Isolate XTTS in its own Python worker environment so its Coqui/Transformers dependency constraints do not alter the Parakeet environment.
- [x] Load an existing local checkpoint when available and download the configured Hugging Face checkpoint into `models/xtts-v2-romanian-v2` when needed.
- [x] Fail clearly when the XTTS worker/runtime cannot start or the checkpoint is incomplete.
- [x] Keep the model lazy and explicitly unloadable so it can participate in VoxPassport model hot-swap and low-VRAM residency policy.
- [x] Wire XTTS into TTS model normalization, activation, runtime adapter selection, adapter exports, startup, and Model Settings UI metadata.

## Romanian text correctness

- [x] Normalize legacy Romanian cedilla characters (`ş`, `ţ`, `Ş`, `Ţ`) to comma-below (`ș`, `ț`, `Ș`, `Ț`) before XTTS tokenization.
- [x] Patch the isolated worker's XTTS tokenizer to accept the checkpoint's `[ro]` language token without modifying site-packages on disk.
- [x] Raise the Romanian tokenizer character limit to 250.
- [x] Bound generated audio-token length dynamically from the input word count to mitigate the Romanian fine-tune stop-token issue.
- [x] Keep live utterances clause-sized rather than feeding long paragraphs into one autoregressive generation.

## Streaming and low-VRAM behavior

- [x] Use XTTS `inference_stream()` and emit PCM chunks as they become available; do not synthesize a complete WAV and fake streaming afterward.
- [x] Use `torch.inference_mode()` and preserve the checkpoint/runtime's supported precision rather than forcing an unverified FP16 conversion.
- [x] Serialize heavy XTTS GPU execution against the existing VoxPassport GPU inference coordinator even though XTTS executes in a separate Python worker.
- [x] Use one XTTS model instance shared by both conversation directions.
- [x] Avoid retaining arbitrary per-request CUDA tensors after synthesis.
- [x] Add a bounded conditioning cache so repeated use of the same voice profile does not recompute speaker latents every utterance.
- [x] Store cached conditioning tensors on CPU; current XTTS `inference_stream()` moves them to the model device for each generation.
- [x] Clear conditioning tensors and the CUDA allocator cache on worker unload.
- [x] Expose worker CUDA allocated/reserved/free memory metrics for hardware soak testing.

## Cross-lingual voice-conditioning workaround

- [x] Support an optional per-profile target-language reference at `conditioning/ro.wav` without replacing the canonical real `reference.wav`.
- [x] Derive the final XTTS profile from the real speaker embedding plus an optional Romanian GPT conditioning latent when both references are available.
- [x] Fall back to ordinary single-reference XTTS conditioning when no target-language reference exists.
- [x] Keep synthetic/derived target-language references separate from canonical voice identity files and make the file naming explicit.
- [x] Add an offline MOSS teacher utility that unloads XTTS, generates Romanian speech from the real reference, and saves only the derived Romanian conditioning WAV/text/metadata.
- [x] Do not add model training/fine-tuning to the live path; teacher-generated Romanian reference creation remains an offline enrollment step.

## Validation and soak testing

- [x] Add unit tests for Romanian cedilla normalization.
- [x] Add tests proving target-language reference selection does not replace the canonical speaker reference.
- [x] Add tests proving conditioning-cache keys change when either reference changes.
- [x] Add tests for dynamic token limits and bounded Romanian text handling.
- [x] Add the pure XTTS helper tests to the existing Runtime Integrity GitHub Actions workflow without installing Coqui or downloading model weights.
- [x] Extend CI compile coverage to the new worker, benchmark, and script sources.
- [x] Add an XTTS-specific soak harness for 50+ alternating English/Romanian cloned turns with time-to-first-byte and CUDA-memory tracking.
- [ ] Run the 50+ turn soak on the actual RTX 2070 and record peak allocated/reserved VRAM and allocator growth.
- [ ] Benchmark ordinary English-reference → Romanian zero-shot identity retention on the RTX 2070.
- [ ] If ordinary cross-lingual conditioning is weak, generate `conditioning/ro.wav` with the MOSS teacher utility and benchmark the hybrid real-speaker + Romanian-GPT conditioning path.
- [ ] Compare XTTS against current Higgs Q4 and MOSS for Romanian naturalness, speaker similarity, first-audio latency, and full bilateral conversational latency.

## Documentation and acceptance

- [x] Document installation of the isolated `.venv-xtts` worker and automatic worker startup.
- [x] Document the two conditioning modes: ordinary zero-shot cloning and real-speaker-embedding + Romanian-conditioning bridge.
- [x] Document that the bridge reference may be generated offline by a heavier model such as MOSS, but MOSS is not required or resident during live XTTS inference.
- [x] Document the required Romanian Unicode normalization and the Romanian model's stop-token limitation.
- [x] Document the 50-turn soak command and adoption criteria.
- [ ] Promote XTTS Romanian to the default TTS only if the RTX 2070 benchmarks show acceptable voice identity, Romanian quality, VRAM headroom, and bilateral latency.

## Implemented files

- `runtime/workers/xtts_romanian/common.py`
- `runtime/workers/xtts_romanian/server.py`
- `runtime/workers/xtts_romanian/requirements.txt`
- `runtime/inference/adapters/tts/xtts_romanian_tts_adapter.py`
- `runtime/inference/server/xtts_main.py`
- `scripts/create_xtts_target_conditioning.py`
- `benchmarks/xtts_romanian_soak.py`
- `tests/test_xtts_romanian.py`
- `docs/xtts-romanian-low-vram.md`
- `install_xtts_worker.bat`
- supporting updates to `run.bat`, `.gitignore`, adapter exports, Model Settings catalog injection, and Runtime Integrity CI.
