# TTS Runtime Profile Supervisor Plan

Status: Future architecture improvement; not required for the completed generic TTS refactor

Purpose: Generalize the current `.venv` + `.venv-xtts` fixed-host arrangement into centrally managed dependency/runtime profiles without collapsing incompatible model libraries into one Python environment or reintroducing model-specific application routing.

## Problem statement

The current TTS architecture is clean at the application boundary: every local model uses `ManifestTtsAdapter` → `voxpassport.tts.v1` → `TtsDriver`.

The remaining topology is intentionally simple but does not scale indefinitely:

```text
primary .venv     -> generic host :8098
isolated XTTS env -> generic host :8099
```

This works while XTTS is the only model family requiring a conflicting Python dependency graph. If additional model families require different Python versions, Transformers constraints, native libraries, or package sets, assigning another permanent port and launcher branch to each environment would recreate hard-coded topology at a different layer.

The solution is **not** to merge all model dependencies into the primary `.venv`. Dependency isolation is desirable. The solution is to make isolated worker lifecycle generic.

## Architectural target

```text
ManifestTtsAdapter
        │
        ▼
TTS Runtime Supervisor
        │
        ├── resolve model manifest
        ├── resolve runtime_profile
        ├── choose interpreter/environment
        ├── start generic worker host on demand
        ├── assign/discover endpoint
        ├── load + health-check driver
        ├── enforce GPU residency policy
        └── stop/unload idle workers
```

Model manifests should describe runtime requirements. They should not permanently own localhost port numbers.

Example target declaration:

```json
{
  "model_id": "xtts-v2-romanian-v2",
  "runtime_profile": "coqui-xtts",
  "driver": {
    "entrypoint": "runtime.workers.tts_host.drivers.xtts_romanian:XttsRomanianDriver"
  }
}
```

Runtime-profile configuration maps the logical profile to an interpreter/environment and provisioning metadata.

## Runtime profile rules

- [ ] Introduce a stable runtime-profile identifier separate from `model_id`.
- [ ] Group models by dependency compatibility; do not create one environment per model by default.
- [ ] Keep a `core` profile for drivers that safely share the primary VoxPassport environment.
- [ ] Keep a `coqui-xtts` profile for XTTS while its dependency graph remains intentionally isolated.
- [ ] Permit future profiles for genuinely incompatible Python versions, native library stacks, or package constraints.
- [ ] Keep model weights outside virtual environments so multiple runtime profiles do not duplicate checkpoint storage.

## Manifest/schema evolution

- [ ] Add `runtime_profile` to the TTS manifest schema.
- [ ] Stop treating `worker.base_url` as permanent model identity.
- [ ] Keep explicit remote/backend URLs inside driver options only when the underlying model really is a proxy to a separate backend.
- [ ] Preserve environment-variable overrides where useful for development/testing.
- [ ] Version the manifest schema if the change cannot be made cleanly within schema version 1.

## Supervisor lifecycle

- [ ] Resolve the target model and runtime profile before TTS activation.
- [ ] Start the required generic host using the profile's Python interpreter.
- [ ] Prefer an OS-assigned free localhost port or another discoverable local transport rather than permanent per-model ports.
- [ ] Wait for worker health before sending `/load`.
- [ ] Load the requested driver/model and verify capabilities.
- [ ] Drain committed speech before incompatible worker changes.
- [ ] Unload/terminate the previous worker when required by GPU residency policy.
- [ ] Keep compatible idle workers alive only when the memory/latency tradeoff justifies it.
- [ ] Shut down idle workers after a configurable timeout.
- [ ] Detect crashed workers and return a clear activation failure without corrupting the active registry slot.

## GPU residency and concurrency

- [ ] Make the supervisor the explicit owner of local TTS worker residency across processes.
- [ ] On low-VRAM systems, enforce one heavyweight local TTS model resident at a time unless measured headroom permits otherwise.
- [ ] Coordinate with the existing main-process heavyweight GPU inference policy so ASR and TTS do not intentionally contend on an 8 GB GPU.
- [ ] Preserve one physical TTS model shared by both conversation directions.
- [ ] Do not interpret multiple worker processes as permission to run multiple heavyweight models concurrently.

## Environment provisioning

- [ ] Replace ad hoc environment creation with reproducible per-profile dependency definitions and locks.
- [ ] Evaluate `uv` or another deterministic environment manager for provisioning isolated profiles.
- [ ] Keep the primary runtime and isolated profiles independently upgradable/testable.
- [ ] Validate the CUDA/PyTorch wheel set per runtime profile.
- [ ] Surface profile installation/repair status in Model Settings or diagnostics.

A single uv workspace is not automatically appropriate if runtime profiles have conflicting requirements, because a workspace shares one resolved dependency set. Independent projects/environments or equivalent per-profile locks are preferable for genuinely conflicting dependency graphs.

## Startup behavior

- [ ] Replace unconditional second-host startup in `run.bat` with supervisor-driven on-demand XTTS startup.
- [ ] Keep `install_xtts_worker.bat` only until runtime-profile provisioning has a generic installer.
- [ ] Eventually replace model-specific installation scripts with a runtime-profile install/repair command.
- [ ] Ensure normal VoxPassport startup does not pay XTTS process/RAM overhead when XTTS is not selected.

## Registry and UI

- [ ] Keep registry active slots model-centric; do not persist ephemeral worker ports as model identity.
- [ ] Expose runtime profile and worker health in diagnostics.
- [ ] Allow Model Settings to show when a model's runtime profile is installed, missing, broken, or running.
- [ ] Keep local TTS model aliases sourced from manifests.

## Validation

- [ ] Unit-test runtime-profile resolution independent of model IDs.
- [ ] Test two models sharing the same runtime profile without spawning duplicate workers unnecessarily.
- [ ] Test a cross-profile OmniVoice ↔ XTTS switch and verify the old GPU model is released.
- [ ] Test worker crash during load and during synthesis.
- [ ] Test port assignment/discovery without fixed 8098/8099 assumptions.
- [ ] Test startup with XTTS installed but unused; XTTS worker should remain stopped until needed.
- [ ] Add Runtime Integrity checks preventing new model-name branches in the supervisor.

## Non-goals

- Do not reintroduce model-specific application adapters.
- Do not merge incompatible Python package sets solely to reduce the number of virtual environments.
- Do not containerize the normal Windows desktop path unless containerization provides a demonstrated operational advantage; local GPU/container packaging would add deployment friction without fixing the core orchestration problem.
- Do not create one virtual environment per model when several models can safely share one runtime profile.

## Acceptance criteria

The supervisor migration is complete when adding a new dependency-incompatible TTS model requires only:

1. a model manifest;
2. an existing or new runtime-profile dependency definition;
3. a driver only if existing drivers cannot express the model;

and requires **no new application adapter, daemon branch, hard-coded port, or model-specific launcher logic**.
