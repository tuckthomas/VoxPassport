# Generic TTS Plugin Architecture Plan

Status: Core implementation complete; legacy base-daemon cleanup pending

Purpose: Refactor VoxPassport TTS integration so the main application depends on a stable VoxPassport TTS protocol and declarative model manifests rather than model-specific adapters and hard-coded routing branches. Model-specific behavior should live behind a narrow driver/plugin boundary, allowing new compatible TTS models to be added with a manifest plus an optional driver instead of edits across the daemon, registry, UI, and activation logic.

## Architecture boundary

- [x] Define a versioned `voxpassport.tts.v1` worker protocol with health, capabilities, load, unload, streamed speech, and metrics endpoints.
- [x] Define a `TtsDriver` interface for model-library-specific behavior (`load`, `unload`, `capabilities`, streamed PCM synthesis, optional voice conditioning, metrics, health).
- [x] Add a generic local TTS worker host that loads one driver by manifest/entrypoint instead of requiring a model-specific server implementation.
- [x] Keep model-specific code inside driver modules; the active daemon sees manifests and `ManifestTtsAdapter`, not XTTS/MOSS/VoxCPM library APIs.

## Declarative manifests

- [x] Add a manifest schema describing model identity, worker transport, endpoint, aliases, languages, sample rate/format, streaming, cloning, transcript requirements, driver entrypoint, registry metadata, and model-specific options.
- [x] Add manifest loader/validation utilities with clear errors for malformed manifests and duplicate aliases/model IDs.
- [x] Add manifests for XTTS Romanian, MOSS-TTS v1.5, and VoxCPM2 as proof cases.
- [x] Make runtime capability discovery authoritative after a worker loads, with manifest metadata used as discovery/startup fallback.

## Generic main-runtime adapter

- [x] Add one `ManifestTtsAdapter` implementing the existing VoxPassport `TtsAdapter` interface for all `voxpassport.tts.v1` models.
- [x] Move common HTTP streaming, PCM framing, health checks, load/unload, profile-reference resolution, preview WAV requests, and capability checks into the generic adapter.
- [x] Support declarative request mapping through worker drivers without another main-daemon adapter class.
- [x] Preserve the existing heavyweight GPU coordinator around local TTS requests.

## Runtime routing and hot swap

- [x] Make the active daemon resolve XTTS/MOSS/VoxCPM by manifest and construct the same generic adapter rather than adding per-model branches to active routing.
- [x] Keep native in-process engines such as OmniVoice/Higgs-native as explicit legacy/native exceptions until they gain protocol workers.
- [ ] Remove the now-unnecessary XTTS/MOSS/VoxCPM compatibility imports and instance fields from inherited `runtime/inference/server/main.py`; the active `tts_plugin_main.py` no longer uses them, but the legacy base class still constructs compatibility-shim instances.
- [x] Make active-model selection resolve manifest model IDs/aliases before falling back to legacy/native normalization.
- [x] Feed manifest aliases into model-manager canonicalization so install/activate/uninstall paths do not need another hard-coded TTS alias table.
- [x] Ensure a newly added manifest can resolve and construct a generic adapter without editing active-daemon routing code.
- [x] Keep one active worker driver per host and hold the runtime lock for a complete committed utterance.
- [x] Revalidate the requested model after acquiring the utterance runtime lock so a concurrent hot-swap cannot change the driver between asynchronous load and synthesis start.

## Driver migrations

- [x] Move active XTTS integration behind an `XttsRomanianDriver` hosted by the generic TTS worker while preserving Romanian normalization, true XTTS streaming, CPU conditioning cache, metrics, and hybrid Romanian GPT conditioning.
- [x] Add one reusable `OpenAiSpeechProxyDriver` and configure MOSS-TTS v1.5 through its manifest rather than a MOSS-specific client adapter implementation.
- [x] Configure VoxCPM2 through the same reusable proxy driver and preserve its published language restrictions as manifest data.
- [x] Keep thin compatibility shims for old `MossTtsAdapter`, `VoxCpmTtsAdapter`, and `XttsRomanianTtsAdapter` imports during migration.
- [x] Remove per-utterance backend health HTTP round-trips from the reusable proxy driver while retaining load-time health validation and failure-state reset.

## Registry and UI metadata

- [x] Bridge manifest metadata into the existing model registry while preserving installed/active/pinned/benchmark state.
- [x] Add runtime capability negotiation so a loaded worker reports languages, streaming, cloning, cross-lingual cloning, transcript requirements, sample rate, and sample format.
- [x] Make the Model Settings catalog discover `voxpassport.tts.v1` entries from backend registry metadata instead of adding an XTTS-specific JavaScript insertion block.
- [x] Make runtime plugin metadata overwrite legacy static fallback card metadata when an older fallback object already exists.
- [x] Avoid introducing new per-model JavaScript branches for migrated manifest-driven TTS models.

## Existing XTTS workflows migrated to the generic protocol

- [x] Start one generic TTS plugin host on port 8098 from `run.bat`; use `.venv-xtts` when installed so the same host can load the XTTS driver.
- [x] Retire the XTTS-specific daemon subclass; keep `xtts_main.py` only as a compatibility entrypoint to the manifest-driven daemon.
- [x] Update the 50-turn XTTS soak harness to send model-aware `voxpassport.tts.v1` load/speech requests.
- [x] Update the offline MOSS teacher utility to switch the generic host to MOSS, create `conditioning/ro.wav`, then unload MOSS instead of instantiating a MOSS-specific application adapter.
- [x] Update XTTS installation/documentation language to describe an XTTS-capable generic TTS host rather than a dedicated XTTS application worker.

## Validation

- [x] Add unit tests for manifest validation, alias resolution, and driver loading.
- [x] Add tests proving XTTS/MOSS/VoxCPM resolve through the same `ManifestTtsAdapter` class.
- [x] Add tests proving MOSS and VoxCPM use the same reusable worker-side proxy driver.
- [x] Add tests proving VoxCPM Romanian exclusion is manifest capability data rather than adapter code.
- [x] Add tests proving a synthetic new manifest can be routed without modifying active-daemon model conditionals.
- [x] Add protocol/controller tests for capabilities, streamed PCM framing, WAV output, cloned reference/transcript/target-conditioning propagation, metrics, health/load/unload behavior using a fake driver.
- [x] Add the new tests to Runtime Integrity CI without downloading model weights or importing Coqui during manifest discovery.
- [x] Preserve and update existing runtime-routing and XTTS helper tests for the new generic boundary.
- [ ] Observe a completed Runtime Integrity CI run for the final commit. The workflow has been updated, but the available GitHub connector has not exposed a push-run result/status for these commits.

## Documentation and acceptance

- [x] Document the rule: adapters normalize transport/protocol, drivers normalize model libraries, manifests describe models.
- [x] Document how to add a new TTS model using only a manifest when an existing driver is compatible.
- [x] Document how to add a small driver plugin when a new model library has genuinely different inference semantics.
- [x] Document protocol endpoints, standard synthesis requests, capability negotiation, voice-profile behavior, hot-swap locking, and native exceptions.
- [ ] Remove the remaining migrated-model compatibility branches/imports from inherited `runtime/inference/server/main.py` so the legacy base implementation itself is also clean rather than merely bypassed by the active manifest daemon.
- [ ] Replace the legacy Studio/manual-synthesis rule `non-OmniVoice => transcript required` with capability-driven transcript validation; XTTS correctly advertises that a reference transcript is not required, but the inherited Studio HTTP handler still has the older coarse rule.
- [ ] Mark the architectural refactor fully complete only after those two inherited-base compatibility items are removed and CI is observed green.

## Implemented files

- `.agents/plans/generic-tts-plugin-architecture-plan.md`
- `runtime/inference/tts_plugins/__init__.py`
- `runtime/inference/tts_plugins/manifest.py`
- `runtime/inference/tts_plugins/registry_bridge.py`
- `runtime/inference/adapters/tts/manifest_tts_adapter.py`
- `runtime/workers/tts_host/__init__.py`
- `runtime/workers/tts_host/protocol.py`
- `runtime/workers/tts_host/driver_loader.py`
- `runtime/workers/tts_host/server.py`
- `runtime/workers/tts_host/drivers/__init__.py`
- `runtime/workers/tts_host/drivers/xtts_romanian.py`
- `runtime/workers/tts_host/drivers/openai_proxy.py`
- `runtime/tts_manifests/xtts-v2-romanian-v2.json`
- `runtime/tts_manifests/moss-tts-1.5.json`
- `runtime/tts_manifests/voxcpm-2.json`
- `runtime/inference/server/tts_plugin_main.py`
- `docs/tts-plugin-architecture.md`
- `tests/test_tts_plugin_architecture.py`
- compatibility/refactor updates to the old XTTS/MOSS/VoxCPM adapter files, `xtts_main.py`, `run.bat`, `install_xtts_worker.bat`, XTTS benchmark/teacher utilities, Model Settings catalog injection, XTTS documentation, adapter exports, and Runtime Integrity CI.

## Remaining compatibility debt

The active runtime path is manifest-driven now. The remaining unchecked work is confined to inherited legacy code in `runtime/inference/server/main.py`: it still imports/constructs the old concrete adapter names (which are now thin generic shims), contains unreachable/bypassed MOSS/VoxCPM routing branches for the active manifest daemon, and applies an older non-OmniVoice transcript rule in Studio/manual synthesis. These should be removed in a focused cleanup of the large base-daemon file rather than being represented as completed work here.
