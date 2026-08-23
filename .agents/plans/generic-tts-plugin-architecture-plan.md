# Generic TTS Plugin Architecture Plan

Status: Implementation complete; final Runtime Integrity execution pending

Purpose: Refactor VoxPassport TTS integration so the main application depends on one stable VoxPassport TTS protocol and declarative model manifests rather than model-specific application adapters, compatibility shims, native exceptions, or hard-coded routing branches. Model-specific behavior lives only behind the worker-side driver boundary, allowing a compatible TTS model to be added with a manifest and, only when genuinely necessary, a small driver.

## Architecture boundary

- [x] Define a versioned `voxpassport.tts.v1` worker protocol with health, capabilities, load, unload, streamed speech, WAV output, and metrics endpoints.
- [x] Define a `TtsDriver` interface for model-library-specific behavior (`load`, `unload`, capabilities, streamed PCM synthesis, optional conditioning, metrics, health).
- [x] Add a generic local TTS worker host that loads one driver by manifest/entrypoint instead of requiring model-specific server implementations.
- [x] Make `ManifestTtsAdapter` the only local TTS adapter visible to the application process.
- [x] Keep all model-library/DLL/backend implementation details inside worker-side drivers.
- [x] Use dependency-specific Python environments only as separate instances of the same generic host/protocol, not as separate architectures.

## Declarative manifests

- [x] Add a manifest schema describing model identity, worker endpoint/environment override, aliases, languages, sample rate/format, streaming, cloning, transcript requirements, driver entrypoint, registry metadata, and model-specific driver options.
- [x] Add manifest loader/validation utilities with clear errors for malformed manifests and duplicate aliases/model IDs.
- [x] Add manifests for every current local TTS path: OmniVoice, Higgs TTS 3, native Higgs Q4_K_M, MOSS-TTS v1.5, VoxCPM2, and XTTS Romanian v2.
- [x] Make runtime capability discovery authoritative after a worker loads, with manifest metadata used as discovery/startup fallback.
- [x] Make TTS manifests the sole built-in catalog for local TTS metadata; remove TTS entries from the general model catalog.

## Generic main-runtime adapter

- [x] Add one `ManifestTtsAdapter` implementing the existing VoxPassport `TtsAdapter` interface for every local `voxpassport.tts.v1` model.
- [x] Move common HTTP streaming, PCM framing, health checks, load/unload, profile-reference resolution, preview WAV requests, capability checks, and target-conditioning path resolution into the generic adapter.
- [x] Support declarative request mapping through worker drivers without another main-daemon adapter class.
- [x] Preserve the heavyweight GPU coordinator around local TTS requests.
- [x] Remove the concrete OmniVoice/Higgs/MOSS/VoxCPM/XTTS application adapter files rather than keeping compatibility shims.

## Runtime routing and hot swap

- [x] Make `runtime/inference/server/main.py` itself manifest-driven; remove the temporary plugin-daemon subclass and XTTS daemon compatibility entrypoint.
- [x] Remove model-name conditionals and substring routing for local TTS from the main daemon.
- [x] Remove all concrete local TTS imports and preconstructed model-specific TTS instance fields from the main daemon.
- [x] Make active-model selection resolve model IDs/aliases through manifests/model-manager canonicalization.
- [x] Feed manifest aliases into model-manager canonicalization so install/activate/uninstall paths do not need hard-coded local TTS aliases.
- [x] Remove native-Higgs registration/detection logic from `ModelManagerController`; native Higgs is an ordinary manifest-driven driver now.
- [x] Make the orchestrator's lower-level hot-swap TTS loader manifest-only instead of retaining a second hidden model-specific dispatch tree.
- [x] Ensure newly added manifests can construct the generic adapter without editing daemon/orchestrator routing code.
- [x] Keep one active driver per generic host and hold the host runtime lock for a complete committed utterance.
- [x] Revalidate the requested model after acquiring the utterance runtime lock so a concurrent hot swap cannot change drivers between asynchronous load and synthesis start.
- [x] Ensure `set_tts_adapter()` unloads the previously active adapter, including cross-host XTTS `:8099` -> primary-host `:8098` switches, so the previous GPU model does not remain resident.

## Driver migrations

- [x] Migrate OmniVoice into `OmniVoiceDriver`, including lazy weight loading, voice cloning, bounded speaker conditioning, PCM/WAV output, unload, and CUDA metrics.
- [x] Migrate native Higgs Q4_K_M/audiocpp into `HiggsNativeDriver`, preserving DLL loading, 5-second reference preparation, `.hspkcache`, clause streaming, native callback PCM, and unload behavior.
- [x] Keep full Higgs TTS 3 behind the reusable HTTP proxy driver with its references-array request mapping declared in the manifest.
- [x] Keep MOSS-TTS v1.5 behind the reusable HTTP proxy driver with its backend/request differences declared in the manifest.
- [x] Keep VoxCPM2 behind the same reusable proxy driver and preserve its language restrictions as manifest data.
- [x] Migrate XTTS Romanian into `XttsRomanianDriver` + internal driver runtime while preserving Romanian normalization, true `inference_stream()`, CPU conditioning cache, metrics, and the hybrid real-speaker/Romanian-GPT conditioning path.
- [x] Remove the XTTS-specific HTTP server and move its remaining runtime/helper code under the generic TTS host driver package.
- [x] Remove the old `runtime/workers/xtts_romanian/` package entirely.
- [x] Remove the old flat `conditioning_ro.wav` compatibility filename; derived conditioning now has one canonical path: `conditioning/ro.wav`.
- [x] Remove per-utterance backend health HTTP round trips from the reusable proxy driver while retaining load-time health validation and failure-state reset.

## Host topology and dependency isolation

- [x] Start the primary generic TTS host from the normal `.venv` on `127.0.0.1:8098`.
- [x] Start the same generic TTS host implementation from `.venv-xtts` on `127.0.0.1:8099` when XTTS is installed.
- [x] Point the XTTS manifest at the isolated `:8099` host while all normal-environment drivers use the primary host.
- [x] Make `run.bat` launch `runtime/inference/server/main.py` directly; remove `tts_plugin_main.py` and `xtts_main.py`.
- [x] Move XTTS requirements under `runtime/workers/tts_host/requirements-xtts.txt` and update `install_xtts_worker.bat` accordingly.

The isolated XTTS environment is an intentional dependency boundary, not legacy compatibility debt. The fixed port mapping is a current launcher implementation, not the desired permanent scaling mechanism.

## Registry and UI metadata

- [x] Bridge manifest metadata into the existing model registry while preserving installed/active/pinned/benchmark state.
- [x] Remove hard-coded local TTS aliases and UI-ID translations from `ModelManagerController`; aliases now originate from manifests.
- [x] Add runtime capability negotiation so a loaded worker reports languages, streaming, cloning, cross-lingual cloning, transcript requirements, sample rate, and sample format.
- [x] Make Model Settings discover `voxpassport.tts.v1` entries from backend registry metadata instead of adding model-specific JavaScript branches.
- [x] Make runtime plugin metadata overwrite older static/fallback card metadata when present.
- [x] Make the UI plugin label host-agnostic rather than assuming every TTS model is served on port 8098.
- [x] Avoid introducing model-specific JavaScript routing for manifest-driven TTS models.

## Voice profiles and transcript requirements

- [x] Keep voice profiles engine-independent (`reference.wav`, optional `reference.txt`, optional target-conditioning files).
- [x] Remove the global enrollment requirement that every voice profile have a transcript.
- [x] Make Studio preview validate reference transcripts from the selected manifest's `reference_transcript_required` capability.
- [x] Make manual synthesis validate reference transcripts from the selected manifest's capability instead of the old `non-OmniVoice => transcript required` rule.
- [x] Keep XTTS's optional `conditioning/{language}.wav` lookup declarative through its manifest.

## Existing XTTS workflows migrated to the clean protocol

- [x] Update the 50-turn XTTS soak harness to target the XTTS-capable generic host on port 8099 and use model-aware `voxpassport.tts.v1` requests.
- [x] Update the offline MOSS teacher utility to explicitly unload XTTS from port 8099, load/generate/unload MOSS through the primary generic host on port 8098, and save only `conditioning/ro.wav` plus metadata.
- [x] Update XTTS installation/documentation language to describe dependency isolation through a second generic host rather than a dedicated XTTS worker architecture.

## Validation

- [x] Add unit tests for manifest validation, alias resolution, and driver loading.
- [x] Add tests proving every local TTS model resolves through `ManifestTtsAdapter` in the application process.
- [x] Add tests proving full Higgs, MOSS, and VoxCPM use the same reusable worker-side proxy driver.
- [x] Add tests proving VoxCPM Romanian exclusion is manifest capability data rather than adapter code.
- [x] Add tests proving OmniVoice, native Higgs, and XTTS driver classes can be discovered without eagerly importing heavyweight model libraries.
- [x] Add tests proving a synthetic new manifest can be routed without modifying main-daemon model conditionals.
- [x] Add protocol/controller tests for capabilities, streamed PCM framing, WAV output, cloned reference/transcript/target-conditioning propagation, metrics, health/load/unload behavior using a fake driver.
- [x] Add tests that fail if deleted concrete TTS adapter/server files reappear.
- [x] Add tests that fail if model-specific local TTS dispatch returns to the main daemon or orchestrator.
- [x] Add tests that fail if TTS entries return to the general built-in catalog.
- [x] Update the existing Runtime Integrity tests and XTTS helper tests to the clean manifest/driver architecture.
- [x] Keep the new tests in Runtime Integrity CI without downloading model weights or importing Coqui during manifest discovery.
- [ ] Observe a completed Runtime Integrity CI run for the final commit. The available GitHub connector has not exposed the final push-triggered run/status; run the workflow or equivalent pytest/compile checks in the local development environment if it remains unavailable here.

## Documentation and acceptance

- [x] Document the rule: application adapter = protocol transport, driver = model/backend implementation, manifest = model declaration.
- [x] Document how to add a model using only a manifest when an existing driver is compatible.
- [x] Document how to add a small driver when a model library has genuinely different inference semantics.
- [x] Document that OmniVoice and native Higgs are not exceptions; they are worker-side drivers using the same protocol.
- [x] Document the two-host dependency-isolation topology and cross-host unload behavior.
- [x] Document protocol endpoints, standard synthesis requests, capability negotiation, voice-profile behavior, hot-swap locking, and registry ownership.
- [x] Remove compatibility shims, compatibility daemon entrypoints, the model-specific XTTS server, native/in-process exceptions, and inherited base-daemon TTS branches.
- [x] Complete the architectural refactor; only final CI observation remains environment-dependent.

## Follow-on topology evolution

The completed refactor solves the **application/model integration architecture**. It does not require the current fixed `.venv`/`:8098` and `.venv-xtts`/`:8099` launcher topology to remain permanent.

The recommended follow-on is tracked separately in:

- `.agents/plans/tts-runtime-profile-supervisor-plan.md`

That future work should:

- preserve dependency isolation;
- replace literal model-to-port coupling with manifest `runtime_profile` metadata;
- launch the generic host under the required interpreter/environment on demand;
- assign/discover worker endpoints dynamically;
- own cross-process TTS GPU residency and idle-worker shutdown;
- group models by dependency compatibility rather than one environment per model.

This is a forward-looking orchestration improvement, not backwards compatibility and not a reason to reopen the deleted adapter architecture.

## Current implementation files

- `.agents/plans/generic-tts-plugin-architecture-plan.md`
- `runtime/inference/tts_plugins/__init__.py`
- `runtime/inference/tts_plugins/manifest.py`
- `runtime/inference/tts_plugins/registry_bridge.py`
- `runtime/inference/adapters/tts/manifest_tts_adapter.py`
- `runtime/inference/adapters/tts/profile_reference.py`
- `runtime/workers/tts_host/__init__.py`
- `runtime/workers/tts_host/protocol.py`
- `runtime/workers/tts_host/driver_loader.py`
- `runtime/workers/tts_host/server.py`
- `runtime/workers/tts_host/requirements-xtts.txt`
- `runtime/workers/tts_host/drivers/omnivoice.py`
- `runtime/workers/tts_host/drivers/higgs_native.py`
- `runtime/workers/tts_host/drivers/openai_proxy.py`
- `runtime/workers/tts_host/drivers/xtts_romanian.py`
- `runtime/workers/tts_host/drivers/xtts_runtime.py`
- `runtime/workers/tts_host/drivers/xtts_common.py`
- `runtime/tts_manifests/omnivoice-stock.json`
- `runtime/tts_manifests/higgs-tts-3.json`
- `runtime/tts_manifests/higgs-tts-3-q4_k_m.json`
- `runtime/tts_manifests/moss-tts-1.5.json`
- `runtime/tts_manifests/voxcpm-2.json`
- `runtime/tts_manifests/xtts-v2-romanian-v2.json`
- `runtime/inference/server/main.py`
- `runtime/inference/server/model_manager_api.py`
- `runtime/inference/pipeline/duplex_orchestrator.py`
- `docs/tts-plugin-architecture.md`
- `docs/xtts-romanian-low-vram.md`
- `tests/test_tts_plugin_architecture.py`
- `tests/integration/test_tts_adapter_integrity.py`
- `tests/test_xtts_romanian.py`
- `benchmarks/xtts_romanian_soak.py`
- `scripts/create_xtts_target_conditioning.py`
- `run.bat`
- `install_xtts_worker.bat`

## Removed legacy architecture

The following paths/classes were deliberately removed rather than retained for compatibility:

- concrete `OmniVoiceTtsAdapter`, `HiggsTtsAdapter`, `HiggsNativeTtsAdapter`, `MossTtsAdapter`, `VoxCpmTtsAdapter`, and `XttsRomanianTtsAdapter` implementations;
- `runtime/inference/server/tts_plugin_main.py`;
- `runtime/inference/server/xtts_main.py`;
- `runtime/workers/xtts_romanian/`;
- model-manager native-Higgs registration logic and local-TTS alias table entries;
- the inherited daemon's model-specific TTS routing/instance fields;
- the blanket non-OmniVoice transcript rule.

No backwards-compatibility layer is intentionally retained for the old local TTS architecture.
