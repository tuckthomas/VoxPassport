# XTTS Romanian Low-VRAM Cloning Plan

Status: Implementation complete; RTX 2070 acceptance testing pending

Purpose: Provide a low-VRAM Romanian/English cloned-voice TTS path around `eduardem/xtts-v2-romanian-v2` with true streaming, cached speaker conditioning, Romanian Unicode normalization, and an optional target-language conditioning bridge—without introducing a model-specific application adapter or separate TTS architecture.

## Model and runtime integration

- [x] Add `xtts-v2-romanian-v2` as a local TTS manifest with Romanian/English, streaming, cloning, licensing, registry, and RTX 2070-oriented planning metadata.
- [x] Route XTTS through the same application-side `ManifestTtsAdapter` and `voxpassport.tts.v1` protocol as every other local TTS model.
- [x] Keep Coqui/XTTS-specific behavior behind `XttsRomanianDriver` and its internal worker-side runtime.
- [x] Isolate XTTS in its own Python environment so Coqui/Transformers constraints do not alter the primary Parakeet/Transformers environment.
- [x] Run the same generic TTS host implementation under `.venv-xtts`; do not maintain an XTTS-specific HTTP server.
- [x] Load an existing local checkpoint when available and download the configured Hugging Face checkpoint into `models/xtts-v2-romanian-v2` when needed.
- [x] Fail clearly when the XTTS worker/runtime cannot start or the checkpoint is incomplete.
- [x] Keep the model lazy and explicitly unloadable so it participates in VoxPassport hot-swap and low-VRAM residency policy.
- [x] Remove the old `XttsRomanianTtsAdapter`, XTTS daemon subclass, and `runtime/workers/xtts_romanian/` package after migration to the generic host/driver boundary.

## Dependency isolation policy

- [x] Treat `.venv-xtts` as a dependency boundary, not a compatibility layer for the old architecture.
- [x] Keep the primary runtime free to follow its own PyTorch/Transformers lifecycle while XTTS uses the dependency range supported by Coqui.
- [x] Document that the current `:8098` / `:8099` arrangement is process topology, not model architecture.
- [ ] Future improvement: replace fixed environment/port selection with a generic TTS runtime supervisor and manifest `runtime_profile` metadata.
- [ ] Future improvement: let the supervisor start isolated workers on demand, assign/discover endpoints, enforce cross-process GPU residency, and shut down idle workers.
- [ ] Future improvement: group models by dependency-compatible runtime profiles rather than creating one environment per model.

The future supervisor work is not required to consider the XTTS model integration complete. The existing isolated environment is intentional; the improvement is centralizing its lifecycle and endpoint assignment.

## Romanian text correctness

- [x] Normalize legacy Romanian cedilla characters (`ş`, `ţ`, `Ş`, `Ţ`) to comma-below (`ș`, `ț`, `Ș`, `Ț`) before XTTS tokenization.
- [x] Patch the isolated worker's XTTS tokenizer to accept the checkpoint's `[ro]` language token without modifying site-packages on disk.
- [x] Raise the Romanian tokenizer character limit to 250.
- [x] Bound generated audio-token length dynamically from input word count to mitigate the Romanian fine-tune stop-token issue.
- [x] Keep live utterances clause-sized rather than feeding long paragraphs into one autoregressive generation.

## Streaming and low-VRAM behavior

- [x] Use XTTS `inference_stream()` and emit PCM chunks as they become available.
- [x] Use `torch.inference_mode()` and preserve the checkpoint/runtime's supported precision rather than forcing an unverified FP16 conversion.
- [x] Serialize heavy XTTS GPU requests against the VoxPassport heavyweight GPU coordinator even though XTTS executes in a separate process.
- [x] Use one XTTS model instance shared by both conversation directions.
- [x] Avoid retaining arbitrary per-request CUDA tensors after synthesis.
- [x] Add a bounded conditioning cache so repeated use of the same profile does not recompute speaker latents every utterance.
- [x] Store cached conditioning tensors on CPU.
- [x] Clear conditioning tensors and CUDA allocator cache on worker unload.
- [x] Expose CUDA allocated/reserved/free memory metrics for hardware soak testing.
- [x] Unload XTTS when switching to a different TTS model so the isolated worker does not silently retain GPU residency.

## Voice-profile and transcript behavior

- [x] Keep XTTS voice profiles engine-independent.
- [x] Do not require a reference transcript for XTTS when its manifest advertises `reference_transcript_required: false`.
- [x] Preserve optional `reference.txt` for profiles because other TTS engines may require it.
- [x] Drive Studio/manual transcript validation from the active manifest rather than a global/non-OmniVoice rule.

## Cross-lingual voice-conditioning workaround

- [x] Support an optional target-language reference at `conditioning/ro.wav` without replacing the canonical real `reference.wav`.
- [x] Derive the final XTTS profile from the real speaker embedding plus optional Romanian GPT conditioning latent when both references are available.
- [x] Fall back to ordinary single-reference XTTS conditioning when no target-language reference exists.
- [x] Keep synthetic/derived target-language references separate from canonical voice identity files.
- [x] Remove the old flat `conditioning_ro.wav` compatibility filename; `conditioning/ro.wav` is canonical.
- [x] Add an offline MOSS teacher utility that unloads XTTS, generates Romanian speech from the real reference, and saves only the derived Romanian conditioning WAV/text/metadata.
- [x] Do not add model training/fine-tuning to the live path; teacher-generated Romanian reference creation remains an offline enrollment step.

## Validation and soak testing

- [x] Add unit tests for Romanian cedilla normalization.
- [x] Add tests proving target-language reference selection does not replace the canonical speaker reference.
- [x] Add tests proving conditioning-cache keys change when either reference changes.
- [x] Add tests for dynamic token limits and bounded Romanian text handling.
- [x] Add pure XTTS helper tests to Runtime Integrity without installing Coqui or downloading model weights.
- [x] Add an XTTS-specific soak harness for 50+ alternating English/Romanian cloned turns with time-to-first-byte and CUDA-memory tracking.
- [x] Point the soak harness at the XTTS-capable generic host used by the current implementation.
- [ ] Run the 50+ turn soak on the actual RTX 2070 and record peak allocated/reserved VRAM and allocator growth.
- [ ] Benchmark ordinary English-reference → Romanian zero-shot identity retention on the RTX 2070.
- [ ] If ordinary cross-lingual conditioning is weak, generate `conditioning/ro.wav` with the MOSS teacher utility and benchmark the hybrid real-speaker + Romanian-GPT conditioning path.
- [ ] Compare XTTS against current Higgs Q4 and MOSS for Romanian naturalness, speaker similarity, first-audio latency, and full bilateral conversational latency.

## Documentation and acceptance

- [x] Document installation of the isolated `.venv-xtts` dependency environment.
- [x] Document that the isolated process uses the same generic TTS host/protocol as other local TTS models.
- [x] Document why dependency isolation is preferable to forcing Coqui into the main environment.
- [x] Document the preferred future runtime-profile supervisor rather than treating fixed port 8099 as the permanent architecture.
- [x] Document the two conditioning modes: ordinary zero-shot cloning and real-speaker-embedding + Romanian-conditioning bridge.
- [x] Document that the bridge reference may be generated offline by MOSS but is not required during live XTTS inference.
- [x] Document Romanian Unicode normalization and the Romanian stop-token limitation.
- [x] Document the 50-turn soak command and adoption criteria.
- [ ] Promote XTTS Romanian to the default TTS only if RTX 2070 benchmarks show acceptable voice identity, Romanian quality, VRAM headroom, and bilateral latency.

## Current implementation files

- `runtime/tts_manifests/xtts-v2-romanian-v2.json`
- `runtime/workers/tts_host/server.py`
- `runtime/workers/tts_host/requirements-xtts.txt`
- `runtime/workers/tts_host/drivers/xtts_romanian.py`
- `runtime/workers/tts_host/drivers/xtts_runtime.py`
- `runtime/workers/tts_host/drivers/xtts_common.py`
- `runtime/inference/adapters/tts/manifest_tts_adapter.py`
- `scripts/create_xtts_target_conditioning.py`
- `benchmarks/xtts_romanian_soak.py`
- `tests/test_xtts_romanian.py`
- `tests/test_tts_plugin_architecture.py`
- `docs/xtts-romanian-low-vram.md`
- `docs/tts-plugin-architecture.md`
- `install_xtts_worker.bat`
- `run.bat`

## Removed legacy XTTS paths

The following are intentionally gone and should not be recreated:

- `runtime/inference/adapters/tts/xtts_romanian_tts_adapter.py`
- `runtime/inference/server/xtts_main.py`
- `runtime/workers/xtts_romanian/`
- the XTTS-specific HTTP server architecture
- blanket transcript requirements based on TTS model name

XTTS is now one driver/runtime profile candidate within the shared local TTS architecture.
