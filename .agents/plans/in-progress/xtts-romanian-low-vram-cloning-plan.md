# XTTS Romanian Low-VRAM Cloning Plan

Status: Implementation complete; runtime-profile provisioning lock and RTX 2070 acceptance testing pending

Purpose: Provide a low-VRAM Romanian/English cloned-voice TTS path around `eduardem/xtts-v2-romanian-v2` with true streaming, cached speaker conditioning, Romanian Unicode normalization, and an optional target-language conditioning bridge—without a model-specific application adapter, fixed worker port, or model-specific launcher.

## Model and runtime integration

- [x] Add `xtts-v2-romanian-v2` as a schema-v2 local TTS manifest.
- [x] Route XTTS through the shared `ManifestTtsAdapter` and `voxpassport.tts.v1` protocol.
- [x] Keep Coqui/XTTS behavior behind `XttsRomanianDriver` and worker-side runtime/helper modules.
- [x] Declare `runtime_profile: coqui-xtts` instead of a worker URL/port.
- [x] Isolate Coqui under `runtime/profiles/coqui-xtts/.venv` so its Transformers constraints do not constrain Parakeet/the primary runtime.
- [x] Use the generic `TtsRuntimeSupervisor` to select the profile interpreter, start the generic host on demand, assign an ephemeral localhost endpoint, health-check, load, and unload XTTS.
- [x] Keep the checkpoint under `models/xtts-v2-romanian-v2`, outside the virtual environment.
- [x] Download the configured Hugging Face checkpoint on first XTTS model load when missing.
- [x] Keep the model lazy and explicitly unloadable for low-VRAM hot swap.
- [x] Remove the old XTTS application adapter, XTTS daemon subclass, XTTS-specific HTTP server, and old worker package.

## Dependency isolation and provisioning

- [x] Treat `coqui-xtts` as a dependency family, not a compatibility layer or one-environment-per-model rule.
- [x] Keep the primary runtime free to follow its own PyTorch/Transformers lifecycle.
- [x] Add `runtime/profiles/coqui-xtts/pyproject.toml` as an independent uv project.
- [x] Pin Torch/TorchAudio/TorchCodec to the explicit cu130 index in that project.
- [x] Use `scripts/manage_runtime_profile.py status|install|repair coqui-xtts` rather than `install_xtts_worker.bat`.
- [x] Prefer `uv sync` when uv is available.
- [x] Keep a declarative venv/pip fallback when uv is unavailable.
- [x] Remove the old root-level `.venv-xtts` path from current code/docs/ignore rules.
- [ ] Generate and commit the initial `runtime/profiles/coqui-xtts/uv.lock` in a connected environment and verify sync on the Windows/CUDA development machine.

## Romanian text correctness

- [x] Normalize legacy Romanian cedilla characters (`ş`, `ţ`, `Ş`, `Ţ`) to comma-below (`ș`, `ț`, `Ș`, `Ț`) before XTTS tokenization.
- [x] Patch the isolated runtime tokenizer to accept the checkpoint's Romanian language token without modifying site-packages on disk.
- [x] Raise the Romanian tokenizer character limit to 250.
- [x] Bound generated audio-token length dynamically from input word count to mitigate the Romanian stop-token issue.
- [x] Keep live utterances clause-sized rather than feeding long paragraphs into one autoregressive generation.

## Streaming and low-VRAM behavior

- [x] Use XTTS `inference_stream()` and emit PCM chunks as they become available.
- [x] Use `torch.inference_mode()` and preserve the checkpoint/runtime's supported precision rather than forcing unverified FP16 conversion.
- [x] Keep actual XTTS synthesis inside the VoxPassport heavyweight GPU coordinator.
- [x] Share one XTTS model instance between both conversation directions.
- [x] Avoid retaining arbitrary per-request CUDA tensors after synthesis.
- [x] Add a bounded conditioning cache.
- [x] Store cached conditioning tensors on CPU.
- [x] Clear conditioning/CUDA allocator state on driver unload.
- [x] Expose CUDA allocated/reserved/free metrics for soak testing.
- [x] Let the runtime supervisor evict/terminate an incompatible active TTS profile before XTTS or its replacement loads.
- [x] Start the XTTS worker only when explicit health validation or synthesis actually needs it.
- [x] Recover a crashed XTTS worker and retry once when failure occurs before first audio.

## Voice-profile and transcript behavior

- [x] Keep XTTS voice profiles engine-independent.
- [x] Do not require a reference transcript when the XTTS manifest advertises `reference_transcript_required: false`.
- [x] Preserve optional `reference.txt` because other TTS engines may require it.
- [x] Drive Studio/manual transcript validation from the active manifest.

## Cross-lingual voice-conditioning workaround

- [x] Support optional target-language conditioning at `conditioning/ro.wav` without replacing canonical `reference.wav`.
- [x] Combine the real speaker embedding with optional Romanian GPT conditioning when both references exist.
- [x] Fall back to ordinary single-reference XTTS conditioning when no target-language reference exists.
- [x] Keep synthetic/derived conditioning separate from canonical speaker identity.
- [x] Keep `conditioning/ro.wav` as the single canonical derived Romanian path.
- [x] Add an offline MOSS teacher utility that asks the runtime supervisor to activate MOSS, generates Romanian speech from the real reference, writes the derived conditioning files, and releases MOSS afterward.
- [x] Keep model training/fine-tuning out of the live path; the MOSS bridge remains an offline enrollment fallback.

## Validation and soak testing

- [x] Add tests for Romanian cedilla normalization.
- [x] Add tests proving target conditioning never replaces the canonical reference.
- [x] Add tests proving conditioning-cache keys change with reference changes.
- [x] Add tests for dynamic token limits and clause bounds.
- [x] Keep pure XTTS helper tests in Runtime Integrity without installing Coqui/model weights.
- [x] Add the XTTS 50+ turn alternating English/Romanian soak harness.
- [x] Make the soak harness resolve XTTS through its manifest/runtime profile with no fixed endpoint argument.
- [x] Add supervisor lifecycle tests covering dynamic worker startup, crash recovery, and cross-profile eviction.
- [ ] Run the 50+ turn soak on the actual RTX 2070 and record peak allocated/reserved VRAM and allocator growth.
- [ ] Benchmark ordinary English-reference → Romanian zero-shot identity retention on the RTX 2070.
- [ ] If ordinary cross-lingual conditioning is weak, generate `conditioning/ro.wav` with the MOSS teacher utility and benchmark the hybrid path.
- [ ] Compare XTTS against Higgs Q4 and MOSS for Romanian naturalness, speaker similarity, first-audio latency, and full bilateral conversational latency.

## Documentation and acceptance

- [x] Document the `coqui-xtts` runtime profile and generic provisioner.
- [x] Document why dependency isolation is preferable to forcing Coqui into the primary environment.
- [x] Document that XTTS has no fixed VoxPassport worker port.
- [x] Document true on-demand worker startup and supervisor crash recovery.
- [x] Document both conditioning modes.
- [x] Document the offline MOSS bridge.
- [x] Document Romanian Unicode normalization and the Romanian stop-token limitation.
- [x] Document the supervisor-based soak command and adoption criteria.
- [ ] Promote XTTS Romanian to the default TTS only if RTX 2070 benchmarks show acceptable identity, Romanian quality, VRAM headroom, and bilateral latency.

## Current implementation files

- `runtime/tts_manifests/xtts-v2-romanian-v2.json`
- `runtime/profiles/runtime_profiles.json`
- `runtime/profiles/coqui-xtts/pyproject.toml`
- `runtime/inference/tts_plugins/runtime_profiles.py`
- `runtime/inference/tts_plugins/runtime_supervisor.py`
- `runtime/inference/tts_plugins/runtime_status.py`
- `runtime/workers/tts_host/server.py`
- `runtime/workers/tts_host/requirements-xtts.txt`
- `runtime/workers/tts_host/drivers/xtts_romanian.py`
- `runtime/workers/tts_host/drivers/xtts_runtime.py`
- `runtime/workers/tts_host/drivers/xtts_common.py`
- `runtime/inference/adapters/tts/manifest_tts_adapter.py`
- `scripts/manage_runtime_profile.py`
- `scripts/create_xtts_target_conditioning.py`
- `benchmarks/xtts_romanian_soak.py`
- `tests/test_xtts_romanian.py`
- `tests/test_tts_plugin_architecture.py`
- `tests/test_tts_runtime_supervisor.py`
- `docs/xtts-romanian-low-vram.md`
- `docs/tts-plugin-architecture.md`

## Removed paths that should not be recreated

- `runtime/inference/adapters/tts/xtts_romanian_tts_adapter.py`
- `runtime/inference/server/xtts_main.py`
- `runtime/workers/xtts_romanian/`
- `install_xtts_worker.bat`
- root-level `.venv-xtts`
- fixed XTTS VoxPassport worker ports
- blanket transcript requirements based on TTS model name

XTTS is now one model/driver assigned to a dependency-compatible runtime profile within the shared local TTS architecture.
