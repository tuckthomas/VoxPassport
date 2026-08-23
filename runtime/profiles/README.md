# TTS Runtime Profiles

Runtime profiles group local TTS workers or backend servers by **dependency compatibility**. They are environment definitions, not models, backend server families, or separate application architectures.

The authoritative profile catalog is `runtime_profiles.json`.

## Current profiles

- `core` — uses the primary VoxPassport `.venv`.
- `coqui-xtts` — isolated Coqui/XTTS project under `coqui-xtts/`.

## Runtime profile versus backend runtime

These terms are intentionally different:

```text
runtime profile
    = which dependency-compatible Python/toolchain environment executes code

backend runtime
    = how a reusable backend server family is launched, health-checked,
      parameterized, exposed to a TTS driver, and supervised

TTS model manifest
    = which model/checkpoint/capabilities/driver/backend runtime are selected
```

Backend runtime definitions live in `runtime/tts_backend_runtimes/`. A backend runtime references a `runtime_profile`; it does not duplicate the profile's dependency definition.

A model manifest can use one worker runtime profile while its backend runtime uses another profile. This is useful when a lightweight proxy driver can live in `core` but the actual backend server has incompatible dependencies.

## Rules

1. Reuse an existing profile whenever the Python/native dependency graph is compatible.
2. Do not create one virtual environment per model by default.
3. Add a new profile only for a genuine incompatibility or isolation requirement: Python version, PyTorch/CUDA wheel generation, Transformers/library constraints, native runtime requirements, or deliberate fault isolation.
4. Model weights stay under the normal model store, not inside profile environments.
5. Profiles never define permanent VoxPassport TTS worker/backend ports. `TtsRuntimeSupervisor` allocates ephemeral localhost endpoints.
6. Model manifests reference the worker profile by `runtime_profile`.
7. Backend runtime definitions independently reference the profile required by their server family.
8. A new model on an existing backend/runtime-profile combination should require only a model manifest.

## Provisioning

Inspect a profile:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
```

Install it:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
```

Repair/recreate an isolated environment:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

## uv projects

For incompatible dependency families, prefer an independent uv project under `runtime/profiles/<profile>/` rather than one shared uv workspace. Independent projects can carry independent lockfiles and incompatible package constraints.

```text
runtime/profiles/coqui-xtts/
  pyproject.toml
  uv.lock      # generated/updated by uv sync
  .venv/       # ignored
```

When `uv` is available, the profile manager uses `uv sync`. When it is unavailable, a profile may declare fallback venv/pip installation steps in `runtime_profiles.json`.

Commit generated lockfiles; never commit profile `.venv` directories.

## Adding a new dependency family

1. Add a profile entry to `runtime_profiles.json`.
2. If using uv, add `runtime/profiles/<profile>/pyproject.toml` and generate its `uv.lock`.
3. Point model manifests and/or reusable backend runtime definitions at the new profile.
4. Do not add supervisor model-name branches or model-specific launch scripts.
5. Run Runtime Integrity plus hardware-specific memory/latency checks before recommending the family as a default.

## Adding a new model does not normally mean adding a profile

If an existing `TtsDriver`, backend runtime, and runtime profile already fit, the new model integration is only a schema-v3 file under `runtime/tts_manifests/` with its model-specific `backend_args`/driver settings.
