# Reusable TTS Backend Runtime Catalog Plan

Status: Architecture and implementation complete; executable CI/local validation pending

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
- [x] Update cross-plan documentation links to the new classified paths.

## Backend runtime contract

- [x] Add a versioned `BackendRuntime` data model and `BackendRuntimeCatalog`.
- [x] Store backend runtime definitions outside individual TTS model manifests.
- [x] Give each backend runtime a stable reusable ID.
- [x] Allow a backend runtime to declare its own dependency `runtime_profile`, independent from the generic worker profile when necessary.
- [x] Support a reusable launch command template and one optional family-level command override environment variable.
- [x] Support a family-level non-loopback remote URL override without putting endpoint topology in each model manifest.
- [x] Define required/optional backend arguments and validate model manifests against that contract before activation.
- [x] Support common command placeholders (`host`, `port`, `project_root`, `model_id`, `backend_runtime_id`, `python`) plus declared `backend_args`.
- [x] Keep health path, startup timeout, endpoint injection option, and process environment on the backend runtime definition.
- [x] Reject unknown backend runtime IDs and missing/unknown backend arguments at manifest/catalog validation time.

## TTS manifest schema

- [x] Upgrade local TTS manifests to backend-runtime-aware schema v3.
- [x] Add optional `backend_runtime` and `backend_args` fields.
- [x] Remove model-owned `backend_process` metadata.
- [x] Remove model-owned local/remote backend URL environment settings for managed proxy families.
- [x] Reject deprecated `backend_process`, `backend_url`, `backend_url_env`, and worker topology in model manifests.
- [x] Keep genuinely model-specific driver settings (payload shape, language mapping, voice/reference fields) in model manifests.
- [x] Preserve direct worker models that do not require a backend runtime.

## Current backend-family migration

- [x] Add reusable backend runtime definitions for full Higgs, MOSS-TTS, and VoxCPM.
- [x] Move Higgs launch/health/remote lifecycle metadata out of `higgs-tts-3.json`.
- [x] Move MOSS launch/health/remote lifecycle metadata out of `moss-tts-1.5.json`.
- [x] Move VoxCPM launch/health/remote lifecycle metadata out of `voxcpm-2.json`.
- [x] Give each current proxy model only a `backend_runtime` reference plus model-specific `backend_args` for backend lifecycle selection.
- [x] Keep OmniVoice, native Higgs Q4, and XTTS as direct worker drivers with no unnecessary backend runtime.
- [x] Remove legacy backend URL environment resolution from `OpenAiSpeechProxyDriver`; endpoint resolution is supervisor-owned only.

## Supervisor integration

- [x] Resolve backend runtime definitions through `BackendRuntimeCatalog`; do not inspect model IDs.
- [x] Resolve backend interpreter/dependencies from the backend runtime's profile when it differs from the worker profile.
- [x] Build backend launch commands by merging the reusable backend runtime template with model `backend_args`.
- [x] Keep dynamic localhost port allocation and runtime-only endpoint injection.
- [x] Preserve process-tree ownership, health probing, dead/unhealthy recycling, rollback, release, idle cleanup, and process-exit cleanup.
- [x] Preserve explicit non-loopback remote endpoints as the only external-backend exception.
- [x] Keep unmanaged loopback endpoints invalid.
- [x] Ensure switching between two models on the same backend family replaces backend/model residency without adding code or topology metadata.
- [x] Keep backend-runtime deployment metadata outside the generic worker process; workers consume only the model manifest and injected endpoint.

## Hot-swap acceptance test

- [x] Add a synthetic backend runtime definition used only by tests.
- [x] Add two synthetic model manifests that reference the same backend runtime but pass different checkpoint arguments.
- [x] Prove both models activate through the same supervisor/backend-runtime code path.
- [x] Prove switching between those models requires no model-name branch and no separate command environment variable.
- [x] Prove each model's backend arguments reach the same reusable launch template.
- [x] Prove backend process replacement follows the declared backend runtime lifecycle policy.
- [x] Prove an unknown backend runtime or missing required argument fails before synthesis.

## Integrity and regression tests

- [x] Add tests for backend-runtime schema validation, duplicates, lookup, required/default/unknown args, and launch argument expansion through the subprocess path.
- [x] Add tests ensuring production model manifests contain no `backend_process` metadata or model-specific `*_TTS_COMMAND` fields.
- [x] Add tests ensuring current proxy manifests reference backend runtime IDs.
- [x] Add tests ensuring the supervisor contains no Higgs/MOSS/VoxCPM model-name dispatch.
- [x] Add tests ensuring backend runtime definitions—not model manifests—own launch/health/remote lifecycle metadata.
- [x] Add the new backend-runtime suite to Runtime Integrity CI.

## Documentation

- [x] Update `README.md` with the manifest-only hot-swap rule.
- [x] Update `docs/architecture.md`.
- [x] Update `docs/tts-plugin-architecture.md`.
- [x] Update `docs/model-registry.md`.
- [x] Update `docs/troubleshooting.md` with backend-runtime configuration/diagnostics.
- [x] Update `runtime/profiles/README.md` to distinguish dependency profiles from backend runtime definitions.
- [x] Update `docs/xtts-romanian-low-vram.md` so MOSS teacher generation uses the reusable MOSS backend runtime.
- [x] Update `docs/model-discovery-agent.md` so future TTS candidates are classified by existing driver/backend-runtime/profile fit.
- [x] Update existing generic-TTS/supervisor plans so they no longer describe per-model backend launch contracts as current architecture.
- [x] Update pending cross-plan links to the classified `.agents/plans/...` paths.

## Completion criteria

The implemented rule is now:

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

No current proxy model owns its own `VOXPASSPORT_<MODEL>_TTS_COMMAND`, fixed port, local URL, process contract, application adapter, or supervisor route.

### Remaining validation

- [ ] Run the Runtime Integrity compile/pytest suite against the final commit. The current GitHub connector returns no combined status checks for the push, and this execution environment does not have a materialized checkout from which to execute the suite directly.
- [ ] Observe the final push-triggered Runtime Integrity workflow as green, or run the equivalent commands in the connected development environment.
- [x] Keep this plan in `.agents/plans/in-progress/` until that executable validation is observed.
- [ ] After the final suite is green, mark this plan complete and move it to `.agents/plans/completed/`.
