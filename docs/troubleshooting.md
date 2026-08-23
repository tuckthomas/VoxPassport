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
- Check the **TTS Runtime Profiles** row in Model Settings and verify only the intended supervised TTS model is active.
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
TTS manifest
  ↓ runtime_profile
TtsRuntimeSupervisor
  ↓ ephemeral worker endpoint
ManifestTtsAdapter ↔ voxpassport.tts.v1
  ↓
TtsDriver
  ↓
model library / DLL / true external backend
```

The main daemon should not import model-specific local TTS adapters.

### TTS model appears in Model Settings but will not load

1. Confirm its manifest exists under `runtime/tts_manifests/`.
2. Check the manifest's `runtime_profile`.
3. Open the Model Settings resource monitor and inspect **TTS Runtime Profiles**.
4. If the profile is **missing**, provision it with `scripts/manage_runtime_profile.py`.
5. If it is **broken**, inspect `data/logs/tts-worker-<profile>.log`.
6. If the driver proxies another service (for example MOSS/full Higgs), verify that true backend is reachable.
7. Verify model weights/checkpoint files are complete.

### Runtime profile is missing

List/check a profile:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
```

Provision it:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
```

Repair/recreate an isolated profile:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

For `coqui-xtts`, the environment lives under:

```text
runtime/profiles/coqui-xtts/.venv
```

Do not recreate the deleted root-level `.venv-xtts` topology.

### Worker port collision

VoxPassport TTS worker ports are dynamically assigned by the supervisor. There is no supported fixed `8098`/`8099` worker mapping anymore.

If worker startup fails, inspect the worker log and diagnostics rather than manually reserving a model-specific port. A true driver backend can still have a configured port (for example an externally launched MOSS/Higgs service); that is separate from the generic VoxPassport worker endpoint.

### Worker unexpectedly exits

The resource monitor reports an unexpectedly exited worker as **broken** while that stale process record exists. On the next safe use, `ensure_active()` recreates the required worker/profile.

Check:

```text
data/logs/tts-worker-<profile>.log
```

If the worker repeatedly exits during load, verify the profile dependency environment and the model/DLL/backend requirements.

### Worker dies during synthesis

If the disconnect occurs before any PCM has been delivered, the generic adapter restarts the runtime profile and retries once. If some speech was already emitted, VoxPassport does not replay the sentence automatically because that could duplicate audible output.

Repeated pre-audio crashes should be treated as a driver/runtime defect and diagnosed from the profile log.

### TTS audio artifacts at chunk boundaries

- Confirm the driver returns real PCM chunks, not concatenated WAV fragments.
- Verify worker sample-rate headers match generated audio.
- Verify playback resampling happens once.
- Reproduce through a standalone preview to separate generation defects from playback/routing defects.

### Voice profile works in one TTS model but not another

Voice profiles are model-independent, but capabilities differ:

- check whether the selected manifest requires a reference transcript;
- XTTS can use a recording without `reference.txt` when its manifest says the transcript is optional;
- other engines may require the exact reference transcript;
- verify target-language and cross-lingual cloning support in the selected manifest.

## XTTS / Coqui runtime profile

### Install/repair XTTS dependencies

XTTS is assigned to `runtime_profile: coqui-xtts`.

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
```

The old `install_xtts_worker.bat` script is intentionally gone.

### Why not install XTTS into the primary `.venv`?

The separation is deliberate dependency isolation. The primary runtime follows a different Hugging Face Transformers lifecycle than Coqui/XTTS. Merging them would couple unrelated ASR and TTS package constraints.

Do not fix an XTTS dependency problem by blindly installing Coqui packages into the main `.venv`.

### uv sync fails

The XTTS profile is an independent uv project under `runtime/profiles/coqui-xtts/`.

- Confirm network/package-index access.
- Verify the PyTorch cu130 index is reachable.
- Verify Python 3.12 is available.
- If uv is not available, the runtime-profile manager uses its declared venv/pip fallback.
- After a successful connected `uv sync`, commit/update the generated `uv.lock` for reproducibility.

### XTTS model load fails

- Verify the `coqui-xtts` profile is installed.
- Verify `models/xtts-v2-romanian-v2/` is complete or check `VOXPASSPORT_XTTS_MODEL_DIR`.
- Check CUDA/PyTorch from the profile interpreter, not from the primary environment.
- Inspect `data/logs/tts-worker-coqui-xtts.log`.

### XTTS remains in VRAM after switching TTS models

That is a bug. A cross-profile replacement should unload XTTS and terminate the incompatible `coqui-xtts` worker before loading the replacement TTS model.

Use the Model Settings resource monitor plus `nvidia-smi`/benchmark telemetry to verify release behavior.

## Native Higgs issues

### Native Higgs DLL cannot load

- Verify `native/audiocpp_engine.dll` or set `VOXPASSPORT_HIGGS_NATIVE_DLL`.
- Verify required CUDA runtime DLLs are discoverable through `CUDA_PATH`/`PATH`.
- Verify the DLL supports the installed GPU architecture.
- Verify the Q4 model package exists under `models/higgs-tts-3-q4_k_m/`.

Native Higgs remains an ordinary worker-side `TtsDriver`; do not add an application adapter to work around DLL errors.

## Hot-swap issues

### TTS switch stalls

- Check the current TTS Runtime Profiles row.
- Allow committed speech to finish before assuming the switch is hung.
- Check the previous worker was unloaded/terminated when crossing profiles.
- Inspect target profile logs for startup/load errors.
- Check VRAM release if moving between heavyweight TTS models.

### Target model fails health validation

The supervisor attempts to restore the previously active TTS manifest after activation failure.

Check whether failure occurred in:

1. runtime-profile interpreter resolution;
2. generic worker startup;
3. `/health` readiness;
4. driver/model `/load`;
5. true external backend health, when the driver is a proxy.

## Session stability

### Memory grows over a long session

- Memory should not grow without bound.
- Check queue depth for accumulation.
- For XTTS, run `benchmarks/xtts_romanian_soak.py` for 50+ alternating turns.
- Distinguish CUDA allocated memory from allocator-reserved memory before labeling growth a leak.

## Runtime Integrity

Useful local checks:

```bat
.venv\Scripts\python.exe -m compileall -q runtime agents tests benchmarks scripts
.venv\Scripts\python.exe -m pytest -q tests/integration tests/test_tts_plugin_architecture.py tests/test_tts_runtime_supervisor.py tests/test_xtts_romanian.py
```

Runtime Integrity includes real lightweight subprocess tests for dynamic worker startup/reuse, cross-profile termination, idle shutdown, load-time crash rollback, and pre-audio synthesis crash recovery without downloading production TTS weights.

Hardware acceptance still requires the target RTX 2070 for real VRAM/latency measurements.
