# Generic TTS Plugin Architecture Plan

Status: In progress

Purpose: Refactor VoxPassport TTS integration so the main application depends on a stable VoxPassport TTS protocol and declarative model manifests rather than model-specific adapters and hard-coded routing branches. Model-specific behavior should live behind a narrow driver/plugin boundary, allowing new compatible TTS models to be added with a manifest plus an optional driver instead of edits across the daemon, registry, UI, and activation logic.

## Architecture boundary

- [ ] Define a versioned `voxpassport.tts.v1` worker protocol with health, capabilities, load, unload, streamed speech, and metrics endpoints.
- [ ] Define a `TtsDriver` interface for model-library-specific behavior (`load`, `unload`, `capabilities`, `synthesize_stream`, optional voice conditioning).
- [ ] Add a generic local TTS worker host that loads one driver by manifest/entrypoint instead of requiring a model-specific server implementation.
- [ ] Keep model-specific code inside driver modules; do not expose XTTS/MOSS/VoxCPM library details to the main daemon.

## Declarative manifests

- [ ] Add a manifest schema describing model identity, worker transport, endpoint, languages, sample rate/format, streaming, cloning, transcript requirements, driver entrypoint, and model-specific options.
- [ ] Add manifest loader/validation utilities with clear errors for malformed manifests.
- [ ] Add manifests for XTTS Romanian, MOSS-TTS v1.5, and VoxCPM2 as proof cases.
- [ ] Make runtime capability discovery authoritative when a worker is running, with manifest metadata used as install/startup fallback.

## Generic main-runtime adapter

- [ ] Add one `ManifestTtsAdapter` / generic worker adapter implementing the existing VoxPassport `TtsAdapter` interface.
- [ ] Move common HTTP streaming, PCM framing, health checks, load/unload, profile-reference resolution, and capability checks into the generic adapter.
- [ ] Support declarative request mapping for ordinary OpenAI-style worker fields and driver-specific optional fields without another main-daemon adapter class.
- [ ] Preserve the existing heavyweight GPU coordinator around local TTS requests.

## Runtime routing and hot swap

- [ ] Replace model-name conditionals for XTTS/MOSS/VoxCPM with manifest lookup and generic adapter construction.
- [ ] Keep native in-process engines such as OmniVoice/Higgs-native as explicit legacy/native exceptions until they gain protocol workers.
- [ ] Remove XTTS/MOSS/VoxCPM-specific imports and instance fields from the main daemon once generic routing is active.
- [ ] Make active-model selection use registry/model ID + manifest rather than substring matching.
- [ ] Ensure model hot-swap can load a generic adapter from a newly added manifest without editing daemon routing code.

## Driver migrations

- [ ] Migrate XTTS Romanian worker logic into an XTTS driver hosted by the generic TTS worker while preserving Romanian normalization, streaming, CPU conditioning cache, and hybrid Romanian GPT conditioning.
- [ ] Add a MOSS driver that maps the generic protocol to its local OpenAI-compatible backend.
- [ ] Add a VoxCPM driver that maps the generic protocol to its local backend and preserves its published language restrictions.
- [ ] Keep compatibility shims for old adapter imports during migration where tests or scripts still reference them.

## Registry and UI metadata

- [ ] Extend model metadata/manifest linkage so UI and runtime labels come from catalog/manifest data instead of duplicated hard-coded aliases.
- [ ] Add runtime capability negotiation so a running worker can report languages, streaming, cloning, sample rate, and transcript requirements.
- [ ] Avoid introducing new per-model JavaScript branches for migrated manifest-driven TTS models.

## Validation

- [ ] Add unit tests for manifest validation and driver loading.
- [ ] Add tests proving XTTS/MOSS/VoxCPM resolve through the same generic adapter class.
- [ ] Add tests proving a synthetic new manifest can be routed without modifying main-daemon model conditionals.
- [ ] Add protocol tests for capabilities, streamed PCM framing, cloned-reference handling, and health/load/unload behavior using a fake driver.
- [ ] Add the new tests to Runtime Integrity CI without downloading model weights.
- [ ] Preserve existing runtime-routing and XTTS helper tests.

## Documentation and acceptance

- [ ] Document the rule: adapters normalize transport/protocol, drivers normalize model libraries, manifests describe models.
- [ ] Document how to add a new TTS model using only a manifest when an existing driver is compatible.
- [ ] Document how to add a small driver plugin when a new model library has genuinely different inference semantics.
- [ ] Mark implementation complete only when XTTS, MOSS, and VoxCPM use the generic boundary and the main daemon no longer contains model-specific routing branches for those three models.
