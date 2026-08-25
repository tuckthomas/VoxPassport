# TTS Runtime Profile Supervisor Plan

Status: Implementation and CI validation complete; connected-environment lock generation and RTX 2070 hardware validation pending

Purpose: Manage dependency-compatible TTS runtime families centrally so local models can hot-swap without hard-coded ports, model-specific launchers, unmanaged localhost GPU backends, or forced dependency convergence.

## Implemented architecture

```text
TTS model manifest
        │
        ├── worker runtime_profile
        ├── optional backend_runtime
        └── model backend_args
                 │
                 ▼
         TtsRuntimeSupervisor
                 │
        ┌────────┴─────────────┐
        ▼                      ▼
 generic TTS worker      BackendRuntimeCatalog
 dependency profile            │
 ephemeral port                ├── backend dependency profile
        │                       ├── reusable launch contract
        │                       ├── health/remote policy
        │                       └── argument contract
        │                                  │
        ▼                                  ▼
     TtsDriver ◄──────────────── managed backend process
                                           ephemeral port
```

Model manifests describe the **model**. Runtime profiles describe **dependency environments**. Backend runtimes describe **reusable server-family lifecycle**. The supervisor owns **process topology and residency**.

## Runtime profile rules

- [x] Introduce stable `runtime_profile` identifiers separate from model IDs.
- [x] Group models by dependency compatibility rather than one environment per model.
- [x] Define `core` for the primary VoxPassport environment.
- [x] Define isolated `coqui-xtts` for Coqui/XTTS.
- [x] Keep weights outside virtual environments.
- [x] Permit per-profile interpreter environment overrides.
- [x] Allow a backend runtime to choose a dependency profile independently from the model's generic worker profile.

## Model manifest / backend runtime split

The earlier schema-v2 `backend_process` design is superseded by `.agents/plans/completed/tts-backend-runtime-catalog-plan.md`.

- [x] Upgrade local TTS model manifests to schema v3.
- [x] Require `runtime_profile` in local TTS model manifests.
- [x] Remove worker URLs/ports from model manifests.
- [x] Remove model-owned `backend_process`, `backend_url`, and `backend_url_env` metadata.
- [x] Add optional model `backend_runtime` plus `backend_args`.
- [x] Add reusable `BackendRuntime` / `BackendRuntimeCatalog` definitions.
- [x] Keep backend family launch/health/remote metadata in backend-runtime definitions.
- [x] Validate backend runtime IDs and argument contracts before activation.
- [x] Keep backend-runtime catalog metadata outside the generic worker boundary.

## Supervisor lifecycle

- [x] Resolve the target model manifest and worker runtime profile before activation.
- [x] Resolve/validate the optional reusable backend runtime and model arguments.
- [x] Resolve the backend runtime's own dependency profile when required.
- [x] Start the same generic `tts_host/server.py` under the selected worker profile.
- [x] Allocate a free `127.0.0.1` worker port dynamically.
- [x] Wait for worker `/health` before loading a driver.
- [x] Build a managed backend launch command from the backend runtime definition plus model `backend_args`.
- [x] Allocate a free localhost backend port dynamically.
- [x] Wait for the backend runtime's declared health endpoint.
- [x] Inject only the ephemeral backend endpoint into the worker as a runtime-only driver override.
- [x] POST `/load` and verify post-load worker/model health.
- [x] Reuse one healthy worker for same-profile model switches.
- [x] Unload the old driver before same-profile replacement.
- [x] Terminate the prior managed backend process tree on model replacement/release.
- [x] Terminate incompatible previous-profile workers before cross-profile activation.
- [x] Roll back to the previous manifest/backend on replacement failure.
- [x] Shut released idle workers down after profile timeout.
- [x] Recreate dead workers/backends and recycle alive-but-unhealthy backends before reuse.
- [x] Retry once when a worker dies before first audio.
- [x] Never automatically replay after partial audio was delivered.
- [x] Terminate owned process trees during process exit as a cleanup safeguard.

## Backend-family ownership

- [x] Treat localhost proxy backend processes as part of supervised TTS residency.
- [x] Keep launch configuration backend-family scoped rather than model scoped.
- [x] Allow one backend runtime definition to launch multiple model manifests with different `backend_args`.
- [x] Support reusable command placeholders: `{host}`, `{port}`, `{project_root}`, `{model_id}`, `{backend_runtime_id}`, `{python}`, plus declared backend args such as `{checkpoint}`.
- [x] Reject unmanaged loopback remote overrides.
- [x] Allow explicit non-loopback remote backend-family overrides because those services do not occupy the local GPU.
- [x] Remove fixed `8095`-`8099` TTS ports.

## True on-demand startup

- [x] Make `ManifestTtsAdapter.load()` a cheap logical activation that does not spawn a worker.
- [x] Start/load physical TTS processes only for explicit health validation or actual synthesis.
- [x] Ensure `CAPTIONS_ONLY` starts without a TTS worker.
- [x] Make `run.bat` start only the main daemon.
- [x] Remove the model-specific XTTS worker installer.

## GPU residency and concurrency

- [x] Make the supervisor the owner of local TTS residency across worker and managed-backend processes.
- [x] Enforce one active supervised local TTS model by default.
- [x] Terminate previous incompatible process residency before loading a replacement.
- [x] Preserve heavyweight GPU inference coordination around actual local TTS synthesis.
- [x] Preserve one physical active TTS model shared by both conversation directions.
- [ ] Verify cross-profile/backend VRAM release with actual model switches on the RTX 2070.

## Runtime profile provisioning

- [x] Add `RuntimeProfile` / `RuntimeProfileCatalog` and `runtime/profiles/runtime_profiles.json`.
- [x] Replace model-specific environment installation with `scripts/manage_runtime_profile.py`.
- [x] Support `status`, `install`, and `repair`.
- [x] Keep `core` tied to the primary `.venv`.
- [x] Put XTTS under `runtime/profiles/coqui-xtts/.venv`.
- [x] Add independent `runtime/profiles/coqui-xtts/pyproject.toml`.
- [x] Prefer `uv sync` when uv is available, with declarative venv/pip fallback.
- [x] Keep incompatible families as independent projects rather than one shared workspace.
- [ ] Generate and commit the first `runtime/profiles/coqui-xtts/uv.lock` from a connected Windows/CUDA development environment.

## Registry / diagnostics

- [x] Keep active registry slots model-centric; do not persist worker/backend endpoints or backend runtime objects as models.
- [x] Keep local TTS aliases sourced from model manifests.
- [x] Report active profile/model plus worker process/PID/endpoint/health.
- [x] Report managed backend model ID, backend runtime ID, backend dependency profile, PID, endpoint, health, and exit state.
- [x] Distinguish unexpected exits from intentional stops.
- [x] Mark the active runtime broken when either worker or managed backend fails.

## Validation

- [x] Test runtime-profile resolution independently from model IDs.
- [x] Assert all local TTS model manifests are schema v3 and contain no process topology.
- [x] Test reusable backend-runtime schema/argument validation.
- [x] Assert the supervisor contains no model-specific TTS names/dispatch branches.
- [x] Test logical adapter load does not spawn unused TTS processes.
- [x] Test same-profile worker reuse and cross-profile termination.
- [x] Test dynamic worker/backend ports.
- [x] Test worker load failure rollback and pre-audio crash recovery.
- [x] Test managed backend startup, endpoint injection, switch/release termination, and alive-but-unhealthy recycling.
- [x] Test unmanaged loopback rejection.
- [x] Test two different model manifests use one backend runtime definition with different checkpoint arguments.
- [x] Add backend-runtime and supervisor suites to Runtime Integrity CI.
- [x] Observe Runtime Integrity green after the architecture migration and during the final Expo/native-audio branch validation.

## Documentation

- [x] Update README, architecture, TTS architecture, model registry, troubleshooting, runtime-profile, and XTTS docs for reusable backend runtimes.
- [x] Keep classified agent plan paths under `.agents/plans/pending`, `in-progress`, and `completed`.
- [x] Remove current documentation that describes model-owned backend launch contracts or fixed local TTS topology.

## Acceptance criteria

Adding a local TTS model now follows:

```text
existing driver + backend runtime + dependency profiles fit
    -> model manifest only

new dependency family
    -> runtime profile

new backend server family
    -> one reusable backend runtime definition

new protocol semantics
    -> one reusable driver if needed
```

No model-specific application adapter, fixed local port, model-name supervisor branch, per-model launch command environment, or unmanaged localhost GPU backend is part of the supported architecture.

Remaining work is environmental: initial XTTS uv lock generation and RTX 2070 residency validation.
