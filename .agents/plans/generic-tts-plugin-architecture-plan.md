# Generic TTS Plugin Architecture Plan

Status: Implementation complete; final Runtime Integrity observation pending

Purpose: Keep VoxPassport local TTS model integration genuinely modular: one application adapter, one stable worker protocol, declarative manifests, worker-side drivers, and supervisor-managed dependency/runtime/process topology. No model-specific application adapters, native exceptions, compatibility shims, fixed local TTS ports, unmanaged localhost GPU backends, or model-specific launcher scripts are retained.

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
- [x] Keep aliases, languages, cloning support, transcript requirements, sample format/rate, driver entrypoint/options, registry metadata, runtime profile, and optional local-backend lifecycle requirements in manifests.
- [x] Make runtime capability discovery authoritative after model load.
- [x] Keep explicit backend URL overrides only for genuine non-loopback remote services.
- [x] Declare local proxy-server startup through model-agnostic `backend_process` metadata rather than fixed localhost URLs.

## Runtime-profile and process supervision

The original generic-driver refactor briefly used fixed generic hosts and independently managed proxy servers. Those intermediate topologies have been replaced by the implemented runtime supervisor.

- [x] Upgrade TTS manifests to schema version 2.
- [x] Add `runtime_profile` to manifests.
- [x] Reject model-owned VoxPassport worker URLs/ports.
- [x] Add `core` and `coqui-xtts` dependency-compatible runtime profiles.
- [x] Add `TtsRuntimeSupervisor` to select interpreters, spawn generic workers on demand, assign dynamic localhost ports, health-check, load, recover, unload, and stop workers.
- [x] Make worker subprocesses use the supervisor's actual manifest catalog path.
- [x] Add generic managed proxy-backend startup from `backend_process.command` or `backend_process.command_env`.
- [x] Allocate proxy-backend ports dynamically and inject those endpoints into drivers as runtime-only options.
- [x] Reject unmanaged loopback proxy URLs.
- [x] Permit explicit non-loopback remote proxy URLs because they do not occupy the local GPU.
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
- [x] Allow the supervisor to inject a managed backend endpoint into the reusable proxy driver without mutating the manifest.
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
- [x] Terminate the prior model's managed local proxy-backend process tree on same-profile or cross-profile replacement.
- [x] Terminate an incompatible previous-profile worker before cross-profile activation.
- [x] Preserve one active supervised local TTS model by default for low-VRAM systems.
- [x] Keep `heavy_gpu_inference()` around actual local TTS generation.
- [x] Roll back the previous TTS manifest and managed backend when replacement activation fails.
- [x] Detect a managed backend that is alive but unhealthy and recycle it before synthesis.
- [x] Restart/retry once when a worker dies before first audio.
- [x] Do not replay after partial audio was emitted.
- [x] Shut idle workers down and terminate supervisor-owned worker/backend children on process exit.

## Registry and UI

- [x] Bridge manifest metadata into the existing registry while preserving model state.
- [x] Keep local TTS aliases out of hard-coded model-manager tables.
- [x] Let Model Settings discover TTS models from backend registry metadata.
- [x] Keep UI routing model-agnostic.
- [x] Add supervised TTS runtime-profile and managed-backend state to resource diagnostics.
- [x] Show TTS runtime profiles in the Model Settings resource monitor as running/ready/missing/broken.
- [x] Mark the active TTS runtime broken when either its generic worker or managed local backend exits or becomes unreachable.

## Existing XTTS workflows

- [x] Make the 50-turn XTTS soak benchmark obtain its worker through the runtime supervisor.
- [x] Remove its fixed endpoint argument/assumption.
- [x] Make the MOSS teacher utility use the supervisor rather than manually unloading fixed XTTS/MOSS hosts.
- [x] Make a local MOSS teacher backend supervisor-owned; allow `VOXPASSPORT_MOSS_TTS_URL` only as an explicit non-loopback remote override.
- [x] Keep only `conditioning/ro.wav` plus its metadata as the derived teacher artifact.

## Validation

- [x] Test manifest schema/alias/driver loading.
- [x] Test every local TTS model uses `ManifestTtsAdapter`.
- [x] Test full Higgs/MOSS/VoxCPM share the reusable proxy driver.
- [x] Test heavyweight driver modules can be discovered without eager heavyweight-library import.
- [x] Test synthetic manifests route without daemon model-name branches.
- [x] Test generic worker protocol/controller behavior with a fake driver.
- [x] Test deleted concrete adapters/servers do not reappear.
- [x] Test runtime-profile resolution and dynamic worker ports.
- [x] Test logical adapter load does not spawn unused TTS processes.
- [x] Test same-profile worker reuse and cross-profile worker termination.
- [x] Test idle shutdown.
- [x] Test worker death during load and during pre-audio synthesis.
- [x] Test managed proxy-backend dynamic startup and endpoint injection.
- [x] Test managed proxy-backend termination on release and replacement.
- [x] Test rejection of unmanaged loopback proxy backends.
- [x] Test a live-but-unhealthy managed proxy backend is terminated/restarted before reuse.
- [x] Add source/manifest integrity checks preventing fixed `8095`-`8099` TTS ports and model-specific supervisor branches.
- [x] Run these tests from Runtime Integrity CI without model downloads.
- [ ] Observe the final push-triggered Runtime Integrity workflow as green; if the connector does not expose it, run the workflow/equivalent pytest locally.

## Documentation and acceptance

- [x] Document: adapter = application protocol boundary; manifest = model/lifecycle declaration; runtime profile = dependency family; supervisor = local process topology/residency; driver = model/backend implementation.
- [x] Update architecture, XTTS, registry/troubleshooting, README/project documentation, and related plans for the supervisor topology.
- [x] Remove documentation that treats `:8095`-`:8099`, `.venv-xtts`, `install_xtts_worker.bat`, or independently managed localhost TTS backends as current architecture.
- [x] Keep explicit historical benchmark results historical rather than rewriting old measurements as current model defaults.

## Current architectural rule

Adding a new compatible local TTS model should require **only a manifest** when an existing driver and runtime profile fit.

If inference semantics are new, add a small worker-side driver. If dependencies are incompatible, add/reuse a runtime profile. If a reusable proxy driver needs a local backend, declare a supervisor launch contract. None of these cases should require an application adapter, daemon branch, fixed local TTS port, model-specific launcher, or unmanaged localhost GPU process.

## Removed legacy/intermediate architecture

The following are deliberately absent:

- concrete `OmniVoiceTtsAdapter`, `HiggsTtsAdapter`, `HiggsNativeTtsAdapter`, `MossTtsAdapter`, `VoxCpmTtsAdapter`, and `XttsRomanianTtsAdapter` implementations;
- `runtime/inference/server/tts_plugin_main.py`;
- `runtime/inference/server/xtts_main.py`;
- `runtime/workers/xtts_romanian/`;
- `install_xtts_worker.bat`;
- local TTS model-name dispatch trees;
- fixed VoxPassport TTS worker ports in manifests or `run.bat`;
- fixed `8095`/`8096`/`8097` proxy-backend addresses;
- unmanaged loopback proxy backends;
- blanket non-OmniVoice transcript rules.

No backwards-compatibility layer is intentionally retained for those paths.
