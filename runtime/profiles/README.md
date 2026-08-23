# TTS Runtime Profiles

Runtime profiles group local TTS drivers by **dependency compatibility**. They are process/environment definitions, not models and not separate application architectures.

The authoritative profile catalog is `runtime_profiles.json`.

## Current profiles

- `core` — uses the primary VoxPassport `.venv`.
- `coqui-xtts` — isolated Coqui/XTTS project under `coqui-xtts/`.

## Rules

1. Reuse an existing profile whenever the model's Python/native dependency graph is compatible.
2. Do not create one virtual environment per model by default.
3. Add a new profile only for a genuine incompatibility or isolation requirement: Python version, PyTorch/CUDA wheel generation, Transformers/library constraints, native runtime requirements, or deliberate fault isolation.
4. Model weights stay under the normal model store, not inside profile environments.
5. Profiles never define permanent VoxPassport TTS worker ports. `TtsRuntimeSupervisor` allocates ephemeral localhost endpoints.
6. Model manifests reference a profile by `runtime_profile` and otherwise remain independent from process topology.
7. A new profile still runs the same `runtime/workers/tts_host/server.py` and `voxpassport.tts.v1` protocol.

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

The `coqui-xtts` profile demonstrates this structure:

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
3. Point one or more TTS manifests at the new `runtime_profile`.
4. Reuse an existing `TtsDriver` if possible; add a driver only for genuinely different inference semantics.
5. Run Runtime Integrity lifecycle tests and hardware-specific memory/latency checks before recommending the profile/model as a default.
