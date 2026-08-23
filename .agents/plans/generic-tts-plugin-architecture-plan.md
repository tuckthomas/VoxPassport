# Generic TTS Plugin Architecture Plan

Status: Implementation complete; final Runtime Integrity observation pending

Purpose: Keep VoxPassport local TTS model integration genuinely modular: one application adapter, one stable worker protocol, declarative manifests, worker-side drivers, and supervisor-managed dependency/runtime profiles. No model-specific application adapters, native exceptions, compatibility shims, fixed VoxPassport worker ports, or model-specific launcher scripts are retained.

## Application boundary

- [x] Define `voxpassport.tts.v1` with health, capabilities, load, unload, streamed speech, WAV output, and metrics.
- [x] Define the worker-side `TtsDriver` interface.
- [x] Make `ManifestTtsAdapter` the only local TTS application adapter.
- [x] Keep model/DLL/backend implementation details inside worker-side drivers.
- [x] Remove the concrete OmniVoice/Higgs/MOSS/VoxCPM/XTTS application adapters.
- [x] Remove local-TTS model-name dispatch from the main daemon and orchestrator.

## Declarative model integration

- [x] Make local TTS manifests the sole built-in local-TTS catalog.
- [x] Give every current local TTS path a manifest: OmniVoice, full Higgs, native Higgs Q4_K_M, MOSS-TTS v1.5, VoxCPM2, and XTTS Romanian v2.
- [x] Keep aliases, languages, cloning support, transcript requirements, sample format/rate, driver entrypoint/options, and registry metadata in manifests.
- [x] Make runtime capability discovery authoritative after model load.
- [x] Keep external backend URLs in driver options only when the driver truly proxies another backend.

## Runtime-profile evolution

The original generic-driver refactor briefly used two fixed generic hosts. That intermediate topology has now been replaced by the implemented runtime supervisor.

- [x] Upgrade TTS manifests to schema version 2.
- [x] Add `runtime_profile` to manifests.
- [x] Reject model-owned VoxPassport worker URLs/ports.
- [x] Add `core` and `coqui-xtts` dependency-compatible runtime profiles.
- [x] Add `TtsRuntimeSupervisor` to select interpreters, spawn generic workers on demand, assign dynamic localhost ports, health-check, load, recover, unload, and stop workers.
- [x] Make `run.bat` start only the main daemon.
- [x] Remove `install_xtts_worker.bat`; isolated environments are provisioned through `scripts/manage_runtime_profile.py`.
- [x] Move XTTS's isolated environment under `runtime/profiles/coqui-xtts/.venv`.
- [x] Add an independent uv project for `coqui-xtts`; do not use one shared workspace for incompatible runtime families.
- [x] Keep venv/pip provisioning as a fallback when uv is unavailable.
- [ ] Generate/commit the first `coqui-xtts/uv.lock` from a connected environment and verify it on the Windows/CUDA development machine.

See `.agents/plans/tts-runtime-profile-supervisor-plan.md` for the detailed supervisor checklist and validation state.

## Driver migrations

- [x] Migrate OmniVoice to `OmniVoiceDriver`.
- [x] Migrate native Higgs/audiocpp Q4 to `HiggsNativeDriver`.
- [x] Use the reusable `OpenAiSpeechProxyDriver` for full Higgs, MOSS, and VoxCPM where their backends expose compatible HTTP semantics.
- [x] Migrate XTTS Romanian to `XttsRomanianDriver` plus its internal runtime/helper modules.
- [x] Preserve XTTS Romanian normalization, true streaming, bounded CPU conditioning cache, metrics, and hybrid real-speaker + target-language GPT conditioning.
- [x] Remove the old XTTS-specific server and `runtime/workers/xtts_romanian/` package.
- [x] Keep one canonical derived target-conditioning path: `conditioning/{language}.wav`.

## Voice profiles and capability-driven behavior

- [x] Keep canonical voice profiles model-independent.
- [x] Keep `reference.txt` optional unless the selected TTS manifest requires it.
- [x] Make Studio/manual synthesis validate transcript requirements from the selected manifest.
- [x] Keep optional XTTS target-language conditioning declarative in its manifest.
- [x] Keep model-specific derived conditioning separate from canonical `reference.wav`.

## Hot swap, residency, and recovery

- [x] Resolve local TTS model IDs through manifests rather than string branches.
- [x] Hold the worker runtime lock for a committed utterance.
- [x] Reuse one worker process for models sharing a runtime profile.
- [x] Unload the prior driver before same-profile replacement.
- [x] Terminate an incompatible previous-profile worker before cross-profile activation.
- [x] Preserve one active supervised local TTS model by default for low-VRAM systems.
- [x] Keep `heavy_gpu_inference()` around actual local TTS generation.
- [x] Roll back the previous TTS manifest when replacement activation fails.
- [x] Restart/retry once when a worker dies before first audio.
- [x] Do not replay after partial audio was emitted.
- [x] Shut idle workers down and terminate supervisor-owned children on process exit.

## Registry and UI

- [x] Bridge manifest metadata into the existing registry while preserving model state.
- [x] Keep local TTS aliases out of hard-coded model-manager tables.
- [x] Let Model Settings discover TTS models from backend registry metadata.
- [x] Keep UI routing model-agnostic.
- [x] Add supervised TTS runtime-profile state to resource diagnostics.
- [x] Show TTS runtime profiles in the Model Settings resource monitor as running/ready/missing/broken.

## Existing XTTS workflows

- [x] Make the 50-turn XTTS soak benchmark obtain its worker through the runtime supervisor.
- [x] Remove its fixed endpoint argument/assumption.
- [x] Make the MOSS teacher utility use the supervisor rather than manually unloading fixed XTTS/MOSS hosts.
- [x] Keep only `conditioning/ro.wav` plus its metadata as the derived teacher artifact.

## Validation

- [x] Test manifest schema/alias/driver loading.
- [x] Test every local TTS model uses `ManifestTtsAdapter`.
- [x] Test full Higgs/MOSS/VoxCPM share the reusable proxy driver.
- [x] Test heavyweight driver modules can be discovered without eager heavyweight-library import.
- [x] Test synthetic manifests route without daemon model-name branches.
- [x] Test generic worker protocol/controller behavior with a fake driver.
- [x] Test deleted concrete adapters/servers do not reappear.
- [x] Test runtime-profile resolution and dynamic ports.
- [x] Test logical adapter load does not spawn an unused worker.
- [x] Test same-profile worker reuse and cross-profile worker termination.
- [x] Test idle shutdown.
- [x] Test worker death during load and during pre-audio synthesis.
- [x] Run these tests from Runtime Integrity CI without model downloads.
- [ ] Observe the final push-triggered Runtime Integrity workflow as green; if the connector does not expose it, run the workflow/equivalent pytest locally.

## Documentation and acceptance

- [x] Document: adapter = application protocol boundary; manifest = model declaration; runtime profile = dependency family; supervisor = process topology; driver = model/backend implementation.
- [x] Update architecture, XTTS, registry/troubleshooting, README/project documentation, and related plans for the supervisor topology.
- [x] Remove documentation that treats `:8098`, `:8099`, `.venv-xtts`, or `install_xtts_worker.bat` as current architecture.
- [x] Keep explicit historical benchmark results historical rather than rewriting old measurements as current model defaults.

## Current architectural rule

Adding a new compatible local TTS model should require **only a manifest** when an existing driver and runtime profile fit.

If inference semantics are new, add a small worker-side driver. If dependencies are incompatible, add/reuse a runtime profile. Neither case should require an application adapter, daemon branch, fixed VoxPassport worker port, or model-specific launcher.

## Removed legacy/intermediate architecture

The following are deliberately absent:

- concrete `OmniVoiceTtsAdapter`, `HiggsTtsAdapter`, `HiggsNativeTtsAdapter`, `MossTtsAdapter`, `VoxCpmTtsAdapter`, and `XttsRomanianTtsAdapter` implementations;
- `runtime/inference/server/tts_plugin_main.py`;
- `runtime/inference/server/xtts_main.py`;
- `runtime/workers/xtts_romanian/`;
- `install_xtts_worker.bat`;
- local TTS model-name dispatch trees;
- fixed VoxPassport TTS worker ports in manifests or `run.bat`;
- blanket non-OmniVoice transcript rules.

No backwards-compatibility layer is intentionally retained for those paths.
