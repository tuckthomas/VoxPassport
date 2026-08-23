# TTS Runtime Profile Supervisor Plan

Status: Implementation complete; connected-environment lock generation, final CI observation, and RTX 2070 hardware validation pending

Purpose: Manage dependency-compatible TTS runtime families centrally so local TTS models can remain modular without hard-coded worker ports, model-specific launchers, unmanaged localhost GPU backends, or forced dependency convergence.

## Implemented architecture

```text
TTS model manifest
        │
        ├── model / capabilities / driver
        ├── runtime_profile
        └── optional backend_process contract
                 │
                 ▼
         TtsRuntimeSupervisor
                 │
        ┌────────┴─────────┐
        ▼                  ▼
 profile: core       profile: coqui-xtts
 primary .venv       isolated profile .venv
        │                  │
        └────────┬─────────┘
                 │
        ┌────────┴────────────────┐
        ▼                         ▼
 generic TTS worker       managed local proxy backend
 ephemeral port           ephemeral port, when required
        │                         │
        ▼                         │
     TtsDriver ───────────────────┘
        │
        ▼
 model / DLL / remote backend
```

Model manifests describe **what runtime family and backend lifecycle a driver requires**. The supervisor decides **where and when local worker/backend processes run**. Ephemeral endpoints are operational state, not model identity.

## Runtime profile rules

- [x] Introduce a stable `runtime_profile` identifier separate from `model_id`.
- [x] Group models by dependency compatibility rather than one environment per model.
- [x] Define a `core` profile for drivers compatible with the primary VoxPassport environment.
- [x] Define a `coqui-xtts` profile for XTTS/Coqui's isolated dependency graph.
- [x] Make future profiles data-driven through `runtime/profiles/runtime_profiles.json` rather than supervisor model branches.
- [x] Keep model weights outside virtual environments so runtime profiles do not duplicate checkpoints.
- [x] Permit per-profile interpreter environment-variable overrides for development/testing.

## Manifest/schema migration

- [x] Upgrade local TTS manifests to schema version 2.
- [x] Require `runtime_profile` in schema-v2 TTS manifests.
- [x] Remove `worker.base_url` from every local TTS manifest.
- [x] Reject legacy `worker` topology in manifest validation.
- [x] Keep true remote backend URL overrides inside driver options.
- [x] Remove fixed localhost proxy-backend ports from the Higgs/MOSS/VoxCPM manifests.
- [x] Add declarative `backend_process.command_env` contracts for local proxy backends.
- [x] Assign OmniVoice, native Higgs, full Higgs proxy, MOSS, and VoxCPM to `core`.
- [x] Assign XTTS Romanian to `coqui-xtts`.

## Supervisor lifecycle

- [x] Resolve the target manifest and runtime profile before worker activation.
- [x] Resolve the configured Python interpreter/environment from the runtime profile.
- [x] Start the same generic `tts_host/server.py` implementation under the selected profile.
- [x] Allocate a free `127.0.0.1` port dynamically rather than assigning permanent TTS worker ports.
- [x] Give workers the supervisor's actual manifest catalog path so synthetic/custom catalogs work through the real subprocess path.
- [x] Wait for `/health` before loading a driver.
- [x] POST `/load` and verify post-load worker/model health.
- [x] Support runtime-only driver-option injection so dynamic backend endpoints never need to be persisted in manifests.
- [x] Reuse one healthy worker when switching between models in the same runtime profile.
- [x] Unload the prior driver before a same-profile model switch.
- [x] Unload and terminate an incompatible previous-profile worker before activating a cross-profile replacement.
- [x] Roll back to the previously active manifest when replacement activation fails.
- [x] Shut released idle workers down after a per-profile configurable timeout.
- [x] Detect dead/unhealthy workers before reuse and recreate them when needed.
- [x] Retry synthesis once when a worker dies before any output audio has been emitted.
- [x] Do not automatically replay an utterance after partial audio has already been delivered.
- [x] Add process-exit cleanup so supervisor-owned workers are terminated even if async idle cleanup cannot complete.
- [x] Write worker stdout/stderr under `data/logs/tts-worker-<profile>.log`.

## Proxy-backend ownership

- [x] Treat localhost proxy backends as part of supervised local TTS residency rather than externally managed exceptions.
- [x] Allocate a dynamic localhost backend port when a manifest declares `backend_process`.
- [x] Resolve a backend launch command generically from a manifest command list or `backend_process.command_env`.
- [x] Support `{host}`, `{port}`, `{project_root}`, `{model_id}`, and `{python}` command placeholders without model-name branches.
- [x] Wait for the backend's declared health endpoint before loading the proxy driver.
- [x] Inject the managed backend endpoint into the worker as a runtime-only driver option.
- [x] Terminate the complete managed backend process tree on model switch, release, recovery, shutdown, and interpreter-exit cleanup.
- [x] Relaunch a managed backend when it dies and the active model is recovered.
- [x] Reject unmanaged loopback proxy URLs instead of allowing local GPU residency outside supervisor control.
- [x] Allow explicit non-loopback backend URLs as remote resources; they do not consume the local GPU and are outside local process ownership by design.
- [x] Remove fixed `8095`/`8096`/`8097` backend addresses from current proxy manifests.

## True on-demand startup

- [x] Make `ManifestTtsAdapter.load()` a cheap logical activation that does not spawn a worker.
- [x] Start/load the physical TTS runtime only for explicit activation health validation or actual synthesis.
- [x] Ensure `CAPTIONS_ONLY` can start without launching a TTS worker.
- [x] Remove unconditional TTS-host startup from `run.bat`.
- [x] Make `run.bat` start only the unified VoxPassport daemon.
- [x] Remove the model-specific `install_xtts_worker.bat` installer.

## GPU residency and concurrency

- [x] Make the supervisor the explicit owner of supervised local TTS residency across runtime-profile and managed-backend processes.
- [x] Enforce one active supervised local TTS model across profiles by default.
- [x] Terminate the incompatible previous TTS profile/backend before loading a replacement, avoiding accidental dual TTS residency on an 8 GB-class GPU.
- [x] Preserve the existing `heavy_gpu_inference()` coordination around actual local TTS synthesis so heavyweight ASR and TTS work do not intentionally contend.
- [x] Preserve one physical active TTS model shared by both conversation directions.
- [x] Do not infer concurrency permission merely because multiple runtime profiles/processes exist.
- [ ] Verify cross-profile VRAM release with real OmniVoice/native-Higgs/XTTS/proxy-backend switches on the RTX 2070.

## Runtime profile provisioning

- [x] Add `RuntimeProfile` / `RuntimeProfileCatalog` and `runtime/profiles/runtime_profiles.json`.
- [x] Replace model-specific environment installation with `scripts/manage_runtime_profile.py`.
- [x] Support `status`, `install`, and `repair` commands.
- [x] Keep `core` tied to the already-installed primary `.venv` rather than duplicating it.
- [x] Move the XTTS environment under `runtime/profiles/coqui-xtts/.venv`.
- [x] Add an independent `runtime/profiles/coqui-xtts/pyproject.toml`.
- [x] Prefer `uv sync` for isolated profiles when uv is available.
- [x] Pin Torch/TorchAudio/TorchCodec to the explicit PyTorch cu130 package index in the XTTS uv project.
- [x] Keep a declarative venv/pip fallback when uv is unavailable.
- [x] Keep incompatible runtime families as independent projects rather than one uv workspace/lock.
- [ ] Generate and commit the initial `runtime/profiles/coqui-xtts/uv.lock` from a connected development environment and verify `uv sync` on Windows/CUDA.

## Registry, diagnostics, and Model Settings

- [x] Keep active registry slots model-centric; do not persist worker/backend endpoints as model identity.
- [x] Keep local TTS aliases sourced from manifests.
- [x] Add `tts_runtime` state to the existing resource diagnostics payload.
- [x] Report active profile/model, profile installation state, worker process/PID, ephemeral endpoint, loaded model, idle timeout, and worker health.
- [x] Report managed proxy backend process/PID, ephemeral endpoint, health path, exit code, and health state.
- [x] Distinguish unexpectedly exited workers and managed backends from intentionally stopped processes.
- [x] Add a full-width **TTS Runtime Profiles** row to the existing Model Settings resource monitor.
- [x] Show profile state as `running`, `ready`, `missing`, or `broken` from backend telemetry rather than a duplicate JavaScript catalog.
- [x] Mark the active runtime broken when either its generic worker or managed proxy backend fails.

## Validation

- [x] Unit-test runtime-profile resolution independently from model IDs.
- [x] Assert all local TTS manifests are schema v2, contain `runtime_profile`, and contain no worker topology.
- [x] Assert the supervisor contains no model-specific local TTS names or dispatch branches.
- [x] Test that logical adapter load does not spawn an unused TTS worker.
- [x] Test two models sharing one profile and verify they reuse one worker process.
- [x] Test a cross-profile switch and verify the previous worker process is terminated.
- [x] Test idle worker shutdown.
- [x] Test a worker process crash during model load and verify rollback to the previous model.
- [x] Test a worker process crash during synthesis before first audio and verify restart/retry.
- [x] Test dynamic worker port allocation without 8098/8099 assumptions.
- [x] Test managed proxy-backend dynamic endpoint assignment.
- [x] Test managed proxy-backend termination on model switch.
- [x] Test managed proxy-backend termination on model release.
- [x] Test rejection of unmanaged loopback proxy backends.
- [x] Add the runtime-supervisor lifecycle suite to Runtime Integrity CI.
- [ ] Observe the final push-triggered Runtime Integrity workflow as green. If GitHub does not expose the final run through the connector, execute the listed compile/pytest checks in the local development environment.

## Documentation

- [x] Update `docs/tts-plugin-architecture.md` to describe the implemented supervisor architecture.
- [x] Update `docs/architecture.md` to include runtime profiles, dynamic workers, crash recovery, and diagnostics.
- [x] Update `docs/xtts-romanian-low-vram.md` to remove fixed-host and model-specific installer assumptions.
- [x] Update root/project documentation and related agent plans so fixed `:8098`/`:8099` topology is not described as current architecture.
- [x] Document generic profile provisioning and the independent uv-project strategy.
- [x] Document the local-proxy rule: supervisor-owned process or explicit non-loopback remote endpoint; unmanaged localhost backends are invalid.

## Non-goals

- Do not reintroduce model-specific application adapters.
- Do not merge incompatible Python package sets solely to reduce virtual-environment count.
- Do not containerize the normal Windows desktop path without a demonstrated operational benefit.
- Do not create one virtual environment per model when models can share a dependency-compatible runtime profile.
- Do not persist ephemeral localhost ports in manifests or registry model identity.
- Do not permit a local GPU-resident proxy backend to outlive or bypass the TTS supervisor.

## Acceptance criteria

The code migration is complete: adding a new dependency-incompatible local TTS model now requires only:

1. a model manifest referencing an existing or new `runtime_profile`;
2. an existing or new runtime-profile dependency definition;
3. a driver only when existing drivers cannot express the model;
4. for a proxy requiring a local backend, a declarative supervisor launch command/command environment.

It requires **no application adapter, daemon model branch, fixed VoxPassport worker/backend port, model-specific launcher/installer, or unmanaged localhost GPU process**.

Remaining acceptance work is environmental rather than architectural: generate/commit the initial XTTS uv lock, observe final CI, and run the real RTX 2070 residency/latency checks.
