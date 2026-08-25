# Reusable TTS Backend Runtime Catalog Plan

Status: Complete — architecture, implementation, documentation, and Runtime Integrity validation are green

Purpose: Separate reusable backend-server lifecycle definitions from individual TTS model manifests so a new model using an already-supported backend family can be added by manifest only, without a new launch environment variable, supervisor branch, application adapter, fixed port, or model-specific process topology.

## Completed architecture

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
    ├── reusable launch template / family-level override
    ├── declared argument contract
    ├── health/startup policy
    ├── remote override policy
    └── endpoint injection option
             │
             ▼
TtsRuntimeSupervisor
    ├── dynamic localhost ports
    ├── launch/reuse/health-check backend process
    ├── inject model-specific arguments
    ├── inject ephemeral endpoint into generic worker
    ├── terminate/recover owned process trees
    └── preserve one active local TTS residency policy
```

## Completed work

- [x] Add versioned `BackendRuntime` / `BackendRuntimeCatalog` definitions outside model manifests.
- [x] Give each backend family a stable reusable ID and independent dependency `runtime_profile`.
- [x] Support reusable launch templates, declared arguments, health/startup policy, endpoint injection and family-level deployment overrides.
- [x] Reject unknown runtime IDs and missing/unknown backend arguments before activation.
- [x] Upgrade local TTS manifests to schema v3 with optional `backend_runtime` + `backend_args`.
- [x] Remove model-owned `backend_process`, `backend_url`, `backend_url_env`, fixed local ports and launch commands.
- [x] Migrate full Higgs, MOSS-TTS and VoxCPM to reusable backend-runtime definitions.
- [x] Keep OmniVoice, native Higgs Q4 and XTTS as direct worker drivers where a backend runtime is unnecessary.
- [x] Keep launch/health/remote lifecycle ownership supervisor-side; generic workers receive only runtime-injected endpoint data.
- [x] Preserve process-tree ownership, health probing, dead/unhealthy recycling, rollback, release, idle cleanup and process-exit cleanup.
- [x] Reject unmanaged loopback remote overrides while permitting explicit non-loopback remote services.
- [x] Prove two synthetic models use the same backend runtime with different checkpoint arguments and no model-name branch.
- [x] Add schema, argument, launch expansion, manifest-integrity and supervisor regression tests.
- [x] Add the backend-runtime suite to Runtime Integrity CI.
- [x] Update README, architecture, TTS architecture, model registry, troubleshooting, runtime-profile, XTTS and model-discovery documentation.
- [x] Observe Runtime Integrity green after the implementation and again during the final Expo/native-audio migration validation.

## Completion rule

```text
New model on an existing supported backend family
    -> model manifest only

New dependency family
    -> runtime profile

New backend server implementation/protocol family
    -> one reusable backend runtime definition
       (plus a reusable driver only if protocol semantics are new)

New supervisor/application routing code
    -> almost never
```

No current proxy model owns its own `VOXPASSPORT_<MODEL>_TTS_COMMAND`, fixed port, local URL, process contract, application adapter, or supervisor route. This plan is complete and retained as an architectural completion record.
