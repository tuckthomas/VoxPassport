# VoxPassport Troubleshooting

## Audio routing issues

### No sound through virtual microphone

1. Verify the virtual audio cable/device is installed and selected.
2. Check the virtual-mic output meter in diagnostics.
3. Confirm the outbound TTS pipeline is active.
4. Confirm the conferencing application is using the virtual device as its microphone.

### Feedback / recursive translation

- Prefer headphones during full-duplex sessions.
- Verify inbound translated TTS is not routed into the captured conference stream.
- Verify virtual-mic output is not recaptured by the physical microphone path.
- Re-check `docs/audio-routing.md`.

## Model errors

### GPU out of memory

- Switch to a lower-memory model/quantization where available.
- On 8 GB-class GPUs, keep MiLMMT and optional diarization on CPU when appropriate.
- Do not keep multiple heavyweight TTS models resident merely because runtime profiles are separate processes.
- Check the **TTS Runtime Profiles** row in Model Settings and verify only the intended supervised TTS model/backend is active.
- Native Higgs Q4 file size is not runtime VRAM usage; CUDA workspaces, activations, caches, and scratch allocations also matter.

### ASR producing nonsense / wrong language

- Verify the intended ASR model is active for the source direction.
- Confirm the capture source is the expected microphone/conference stream.
- Test ASR independently before debugging translation/TTS.

### Translation quality poor

- Verify the active translation model and direction.
- Verify the source ASR transcript first.
- Compare MiLMMT 1B with a heavier model only when hardware permits.

## Local TTS architecture diagnostics

Every local TTS model reaches the application through:

```text
TTS model manifest
  │ runtime_profile
  │ optional backend_runtime + backend_args
  ▼
TtsRuntimeSupervisor
  ├─ ephemeral generic worker
  └─ BackendRuntimeCatalog -> ephemeral managed backend, when required
       ↓
ManifestTtsAdapter ↔ voxpassport.tts.v1
       ↓
TtsDriver
       ↓
model library / DLL / explicit remote backend
```

The main daemon should not import model-specific local TTS adapters.

### TTS model appears in Model Settings but will not load

1. Confirm its schema-v3 manifest exists under `runtime/tts_manifests/`.
2. Check the manifest's worker `runtime_profile`.
3. If it declares `backend_runtime`, confirm that ID exists under `runtime/tts_backend_runtimes/` and its required `backend_args` are present.
4. Inspect **TTS Runtime Profiles** in Model Settings.
5. If the worker/backend dependency profile is **missing**, provision it with `scripts/manage_runtime_profile.py`.
6. If the worker is **broken**, inspect `data/logs/tts-worker-<profile>.log`.
7. If a managed backend is **broken**, inspect `data/logs/tts-backend-<backend-runtime>-<model-id>.log`.
8. Verify model weights/checkpoint files are complete.

## Runtime profile is missing

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

For `coqui-xtts`, the environment lives under:

```text
runtime/profiles/coqui-xtts/.venv
```

Do not recreate the deleted root-level `.venv-xtts` topology.

## Backend runtime issues

Full Higgs, MOSS, and VoxCPM currently use reusable OpenAI-style backend runtime families:

```text
higgs-openai-server
moss-openai-server
voxcpm-openai-server
```

Their definitions are under `runtime/tts_backend_runtimes/`. A backend runtime—not each model manifest—owns launch/health/remote lifecycle metadata.

### Family command configuration

Current deployment-level local command overrides are:

```text
VOXPASSPORT_TTS_BACKEND_HIGGS_COMMAND
VOXPASSPORT_TTS_BACKEND_MOSS_COMMAND
VOXPASSPORT_TTS_BACKEND_VOXCPM_COMMAND
```

These are **backend-family** settings. Configure a server implementation once. A second model/checkpoint using that backend family should require only another model manifest with different `backend_args`.

A command override may be a JSON string array (preferred) or shell-style string. Available placeholders are:

```text
{host}
{port}
{project_root}
{model_id}
{backend_runtime_id}
{python}
```

Every argument declared by the backend runtime is also available as a placeholder. Current proxy families declare `{checkpoint}`.

Example shape:

```text
["C:\\path\\to\\python.exe", "-m", "some_backend", "--host", "{host}", "--port", "{port}", "--model", "{checkpoint}"]
```

The exact command is backend-package dependent. If a backend family acquires a canonical portable launch command, it should be stored directly in its backend runtime definition instead of requiring a command environment override.

### Error: backend runtime is unknown

The model manifest references a `backend_runtime` ID that is not registered in `runtime/tts_backend_runtimes/`.

Fix the backend runtime ID or add one reusable backend runtime definition for that server implementation. Do not add a model-name branch to the supervisor.

### Error: required backend argument is missing

The backend runtime declares a required argument such as `checkpoint`, but the model manifest did not provide it under `backend_args`.

Example:

```json
{
  "backend_runtime": "moss-openai-server",
  "backend_args": {
    "checkpoint": "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"
  }
}
```

Argument validation occurs before synthesis.

### Error: no backend-family launch command is configured

The selected backend runtime has no static reusable launch command and its family command override is unset.

Configure the backend **family** once. Do not add a new environment variable to the model manifest, and do not work around the error by starting an unmanaged localhost GPU server.

### Error: unmanaged local backend

A backend runtime's remote URL override resolves to localhost/loopback. That is intentionally rejected because the local GPU process would sit outside supervisor ownership.

Use either:

- the backend runtime's local launch command/command override; or
- its explicit **non-loopback remote** URL override.

### Remote backend family overrides

Current family-level remote overrides are:

```text
VOXPASSPORT_TTS_BACKEND_HIGGS_URL
VOXPASSPORT_TTS_BACKEND_MOSS_URL
VOXPASSPORT_TTS_BACKEND_VOXCPM_URL
```

A non-loopback service executes elsewhere, so its process lifecycle is outside local GPU residency.

### Managed backend unexpectedly exits or becomes unhealthy

The resource monitor marks the active TTS runtime **broken** when either the generic worker or managed backend exits/becomes unreachable.

Check:

```text
data/logs/tts-backend-<backend-runtime>-<model-id>.log
```

An apparently live backend whose health endpoint fails is recycled before reuse. A replacement receives a new ephemeral port and is reinjected into the proxy driver.

### Backend remains in VRAM after switching models

That is a bug for a supervisor-owned local backend. Switching/releasing the model terminates the complete managed backend process tree before replacement residency is established.

Verify with the TTS Runtime Profiles monitor and `nvidia-smi`.

### Worker/backend port collision

Both generic worker ports and local backend ports are dynamically assigned. There is no supported fixed `8095`-`8099` TTS topology.

## Worker issues

### Worker unexpectedly exits

The resource monitor reports an unexpectedly exited worker as **broken**. The next safe activation/use recreates the required worker profile.

Check:

```text
data/logs/tts-worker-<profile>.log
```

### Worker dies during synthesis

If the disconnect occurs before any PCM has been delivered, the generic adapter restarts the supervised runtime and retries once. If some speech was already emitted, VoxPassport does not replay the sentence automatically.

### TTS audio artifacts at chunk boundaries

- Confirm the driver returns real PCM chunks, not concatenated WAV fragments.
- Verify worker sample-rate headers match generated audio.
- Verify playback resampling happens once.
- Reproduce through standalone preview to separate generation defects from playback/routing defects.

### Voice profile works in one TTS model but not another

Voice profiles are model-independent, but capabilities differ:

- check whether the selected manifest requires a reference transcript;
- XTTS can use a recording without `reference.txt` when its manifest says the transcript is optional;
- other engines may require the exact reference transcript;
- verify target-language and cross-lingual cloning support.

## XTTS / Coqui runtime profile

### Install/repair XTTS dependencies

XTTS uses `runtime_profile: coqui-xtts`:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
```

The old `install_xtts_worker.bat` script is intentionally gone.

### Why not install XTTS into the primary `.venv`?

The separation is deliberate dependency isolation. The primary runtime and Coqui/XTTS have different package constraints. Do not fix an XTTS dependency problem by blindly installing Coqui packages into the main `.venv`.

### uv sync fails

- Confirm network/package-index access.
- Verify the PyTorch cu130 index is reachable.
- Verify Python 3.12 is available.
- If uv is unavailable, the profile manager uses its declared venv/pip fallback.
- After a successful connected sync, commit/update `runtime/profiles/coqui-xtts/uv.lock`.

### XTTS model load fails

- Verify the `coqui-xtts` profile is installed.
- Verify `models/xtts-v2-romanian-v2/` is complete or check `VOXPASSPORT_XTTS_MODEL_DIR`.
- Check CUDA/PyTorch from the profile interpreter, not the primary environment.
- Inspect `data/logs/tts-worker-coqui-xtts.log`.

### XTTS remains in VRAM after switching TTS models

That is a bug. A cross-profile replacement should unload XTTS and terminate the incompatible `coqui-xtts` worker before loading the replacement.

## Native Higgs issues

### Native Higgs DLL cannot load

- Verify `native/audiocpp_engine.dll` or set `VOXPASSPORT_HIGGS_NATIVE_DLL`.
- Verify required CUDA runtime DLLs are discoverable through `CUDA_PATH`/`PATH`.
- Verify the DLL supports the installed GPU architecture.
- Verify the Q4 model package exists under `models/higgs-tts-3-q4_k_m/`.

Native Higgs remains an ordinary worker-side `TtsDriver`; do not add an application adapter to work around DLL errors.

## Hot-swap issues

### Adding a new checkpoint/model still appears to require a new launch command

Check whether the model really uses a **new backend server implementation**.

- If it uses an existing backend family, add only another schema-v3 model manifest referencing the existing `backend_runtime` and supply new `backend_args`.
- If it needs a genuinely new dependency family, add/reuse a runtime profile.
- If it needs a genuinely new server implementation, add one reusable backend runtime definition.
- If its inference HTTP/library semantics differ, add/reuse a `TtsDriver`.

Do not add `VOXPASSPORT_<MODEL>_TTS_COMMAND`, another fixed port, or a supervisor model-name branch.

### TTS switch stalls

- Check the TTS Runtime Profiles row.
- Allow committed speech to finish before assuming the switch is hung.
- Check the previous worker/backend was unloaded/terminated as required.
- Inspect target worker/backend logs for startup/load errors.
- Check VRAM release when moving between heavyweight models.

### Target model fails health validation

The supervisor attempts rollback after activation failure. Check whether failure occurred in:

1. model manifest/backend-argument validation;
2. worker runtime-profile resolution;
3. backend runtime-profile resolution;
4. managed backend command/startup/health;
5. generic worker startup;
6. driver/model `/load`;
7. explicit non-loopback remote backend availability.

## Session stability

### Memory grows over a long session

- Check queue depth for accumulation.
- For XTTS, run `benchmarks/xtts_romanian_soak.py` for 50+ alternating turns.
- Distinguish CUDA allocated memory from allocator-reserved memory before labeling growth a leak.

## Runtime Integrity

Useful local checks:

```bat
.venv\Scripts\python.exe -m compileall -q runtime agents tests benchmarks scripts
.venv\Scripts\python.exe -m pytest -q tests/integration tests/test_tts_backend_runtime_catalog.py tests/test_tts_plugin_architecture.py tests/test_tts_runtime_supervisor.py tests/test_tts_residency_contract.py tests/test_xtts_romanian.py
```

Runtime Integrity covers model-manifest/backend-runtime validation, synthetic two-model one-backend-family hot swapping, dynamic worker/backend startup, managed process termination/recycling, cross-profile termination, rollback, and pre-audio recovery without downloading production TTS weights.

Hardware acceptance still requires the target RTX 2070 for real VRAM/latency measurements.
