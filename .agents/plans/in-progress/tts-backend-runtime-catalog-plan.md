# Reusable TTS Backend Runtime Catalog Plan

Status: In progress

Purpose: Finish the TTS hot-swap refactor by separating reusable backend-server lifecycle definitions from individual model manifests. A new model using an already-supported backend family must be addable by manifest only, without a new launch environment variable, launch command, supervisor branch, application adapter, or model-specific process topology.

## Architectural target

```text
TTS model manifest
    │
    ├── model identity / capabilities / driver settings
    ├── runtime_profile
    ├── backend_runtime: <reusable backend family, optional>
    └── backend_args: <model-specific arguments>
             │
             ▼
BackendRuntimeCatalog
    ├── backend runtime ID
    ├── backend dependency/runtime profile
    ├── reusable launch template or one family-level command override
    ├── declared argument contract
    ├── health endpoint / startup policy
    ├── remote endpoint override policy
    └── endpoint injection option
             │
             ▼
TtsRuntimeSupervisor
    ├── allocate dynamic localhost ports
    ├── launch/reuse/health-check backend process
    ├── inject model-specific backend arguments
    ├── inject ephemeral endpoint into generic TTS worker
    ├── terminate/recover process trees
    └── preserve one active local TTS residency policy
```

## Plan-directory organization

- [x] Create `.agents/plans/pending/`.
- [x] Create `.agents/plans/in-progress/`.
- [x] Create `.agents/plans/completed/`.
- [x] Move future/unstarted feature plans to `pending/`.
- [x] Move plans with remaining environment/hardware acceptance work to `in-progress/`.
- [x] Keep `completed/` separate even if no previous plan is honestly complete yet.
- [x] Delete root-level plan copies after their classified copies exist.
- [ ] Update cross-plan documentation links to the new classified paths.

## Backend runtime contract

- [ ] Add a versioned `BackendRuntime` data model and `BackendRuntimeCatalog`.
- [ ] Store backend runtime definitions outside individual TTS model manifests.
- [ ] Give each backend runtime a stable reusable ID.
- [ ] Allow a backend runtime to declare its own dependency `runtime_profile`, independent from the generic worker profile when necessary.
- [ ] Support a reusable launch command template and one optional family-level command override environment variable.
- [ ] Support a family-level non-loopback remote URL override without putting endpoint topology in each model manifest.
- [ ] Define required/optional backend arguments and validate model manifests against that contract before activation.
- [ ] Support common command placeholders (`host`, `port`, `project_root`, `model_id`, `python`) plus declared `backend_args`.
- [ ] Keep health path, startup timeout, endpoint injection option, and process environment on the backend runtime definition.
- [ ] Reject unknown backend runtime IDs and missing required backend arguments at manifest/catalog validation time.

## TTS manifest schema

- [ ] Upgrade the current TTS manifest schema to the new backend-runtime-aware version.
- [ ] Add optional `backend_runtime` and `backend_args` fields.
- [ ] Remove model-owned `backend_process` metadata.
- [ ] Remove model-owned local/remote backend URL environment settings for managed proxy families.
- [ ] Reject deprecated `backend_process`, local backend URL topology, and model-specific backend launch command metadata.
- [ ] Keep driver settings that are genuinely model-specific (payload shape, language mapping, voice/reference fields) in the model manifest.
- [ ] Preserve models that run directly inside the generic worker without a backend runtime.

## Current backend-family migration

- [ ] Add reusable backend runtime definitions for full Higgs, MOSS-TTS, and VoxCPM.
- [ ] Move the current Higgs launch/health/remote-override lifecycle metadata out of `higgs-tts-3.json`.
- [ ] Move the current MOSS launch/health/remote-override lifecycle metadata out of `moss-tts-1.5.json`.
- [ ] Move the current VoxCPM launch/health/remote-override lifecycle metadata out of `voxcpm-2.json`.
- [ ] Give each current proxy model only a `backend_runtime` reference plus its model-specific `backend_args`.
- [ ] Keep OmniVoice, native Higgs Q4, and XTTS as direct worker drivers with no unnecessary backend runtime.

## Supervisor integration

- [ ] Resolve backend runtime definitions through `BackendRuntimeCatalog`; do not inspect model IDs.
- [ ] Resolve backend interpreter/dependencies from the backend runtime's profile when it differs from the worker profile.
- [ ] Build backend launch commands by merging the reusable backend runtime template with model `backend_args`.
- [ ] Keep dynamic localhost port allocation and runtime-only endpoint injection.
- [ ] Preserve process-tree ownership, health probing, dead/unhealthy recycling, rollback, release, idle cleanup, and process-exit cleanup.
- [ ] Preserve explicit non-loopback remote endpoints as the only external-backend exception.
- [ ] Keep unmanaged loopback endpoints invalid.
- [ ] Ensure switching between two models on the same backend family can replace model/backend residency without adding code or topology metadata.

## Hot-swap acceptance test

- [ ] Add a synthetic backend runtime definition used only by tests.
- [ ] Add two synthetic model manifests that reference the same backend runtime but pass different backend arguments/checkpoints.
- [ ] Prove both models activate through the same supervisor/backend-runtime code path.
- [ ] Prove switching between those two models requires no model-name branch and no separate command environment variable.
- [ ] Prove the second model's backend arguments reach the reusable launch template.
- [ ] Prove backend process replacement/reuse follows the declared backend runtime lifecycle policy.
- [ ] Prove an unknown backend runtime or missing required argument fails before model synthesis.

## Integrity and regression tests

- [ ] Add tests for backend-runtime schema validation, duplicates, lookup, required args, and placeholder expansion.
- [ ] Add tests ensuring production model manifests contain no `backend_process` metadata or model-specific `*_TTS_COMMAND` fields.
- [ ] Add tests ensuring current proxy manifests reference backend runtime IDs.
- [ ] Add tests ensuring the supervisor contains no Higgs/MOSS/VoxCPM model-name dispatch.
- [ ] Add tests ensuring backend runtime definitions—not model manifests—own launch/health/remote endpoint lifecycle metadata.
- [ ] Add the new tests to Runtime Integrity CI.

## Documentation

- [ ] Update `README.md` with the true hot-swap rule.
- [ ] Update `docs/architecture.md`.
- [ ] Update `docs/tts-plugin-architecture.md`.
- [ ] Update `docs/model-registry.md`.
- [ ] Update `docs/troubleshooting.md` with backend-runtime configuration/diagnostics.
- [ ] Update `runtime/profiles/README.md` to distinguish worker dependency profiles from backend runtime definitions.
- [ ] Update the existing TTS generic/supervisor plans so they do not describe per-model backend launch contracts as the current architecture.

## Completion criteria

The implementation is complete when the rule is:

```text
New model on an existing supported backend family
    -> model manifest only

New dependency family
    -> runtime profile

New backend server implementation/protocol family
    -> one reusable backend runtime definition (and a driver only if protocol semantics are new)

New supervisor/application routing code
    -> almost never
```

No current proxy model may require its own `VOXPASSPORT_<MODEL>_TTS_COMMAND` wiring as part of model integration.

- [ ] Run static/unit/integration tests available in the repository environment.
- [ ] Observe Runtime Integrity CI green when available through GitHub.
- [ ] If completion depends only on validation unavailable from this execution environment, keep this plan in `in-progress/` and record the exact remaining checks.
- [ ] If all architectural and executable validation is complete, mark this plan complete and move it to `.agents/plans/completed/`.
