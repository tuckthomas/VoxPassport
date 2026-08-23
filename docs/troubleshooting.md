# VoxPassport Troubleshooting

## Audio routing issues

### No sound through virtual microphone

1. Verify the virtual audio cable/device is installed and selected.
2. Check the virtual-mic output meter in diagnostics.
3. Confirm the outbound TTS pipeline is active.
4. Confirm the conferencing application is using the virtual device as its microphone.

### Feedback / echo

1. Prefer headphones during full-duplex sessions.
2. Verify inbound translated TTS is not routed to a device that is also captured as conference audio.
3. Check that generated TTS is excluded from the corresponding ASR capture path.
4. Verify any configured AEC/noise-processing path is operating as expected.

### Recursive translation loop

1. Stop the live pipeline if generated translated speech is being retranscribed.
2. Verify the inbound capture source does not include local translated playback.
3. Verify the physical microphone path is not capturing virtual-mic output.
4. Re-check the bus routing rules in `docs/audio-routing.md`.

## Model errors

### GPU out of memory

- Switch to a lower-memory model or quantization where available.
- On 8 GB-class GPUs, keep MiLMMT and optional diarization on CPU when appropriate so VRAM remains available for latency-sensitive speech models.
- Do not keep multiple heavyweight TTS models resident merely because their workers are separate processes.
- When switching TTS models, verify the previous worker actually unloaded its model and released GPU allocations.
- Native Higgs Q4 weight size is not the same as runtime VRAM usage; KV cache, activations, CUDA workspaces, and model scratch buffers also consume memory.

### ASR producing nonsense / wrong language

- Verify the intended ASR model is active for the source direction.
- Confirm the capture source is actually the intended microphone/conference stream.
- Test the ASR model against a known audio sample before debugging translation or TTS.

### Translation quality poor

- Check the active translation model and direction.
- Compare MiLMMT 1B with the heavier 4B option when hardware permits.
- Verify the ASR transcript first; translation cannot repair a badly recognized source sentence reliably.

## Local TTS architecture diagnostics

Every local TTS model should appear to the main process through `ManifestTtsAdapter`. The main daemon should not import OmniVoice, Higgs, XTTS, MOSS, or VoxCPM application adapters directly.

If a TTS model fails, diagnose the layers separately:

```text
Manifest / registry resolution
        ↓
ManifestTtsAdapter
        ↓
voxpassport.tts.v1 generic host
        ↓
TtsDriver
        ↓
model library / DLL / local backend
```

### TTS model appears in Model Settings but will not load

1. Confirm its manifest exists in `runtime/tts_manifests/`.
2. Check that the manifest's driver entrypoint is importable in the worker environment.
3. Check the generic worker `/health` endpoint.
4. Send or inspect `/load` for the specific model ID.
5. If the driver proxies another local service, verify that backend is running and reachable.
6. Check the worker process output for the underlying library/DLL error.

### TTS audio artifacts at chunk boundaries

- Confirm the driver is returning real PCM chunks rather than concatenated WAV fragments.
- Verify the sample-rate headers reported by the worker match the actual generated audio.
- Verify playback resampling occurs once per chunk and is not being repeated unnecessarily.
- Reproduce with a standalone preview request to determine whether the defect is in generation or playback.

### Voice profile works in one TTS model but not another

Voice profiles are model-independent, but model capabilities differ.

- Check whether the selected manifest requires a reference transcript.
- A missing `reference.txt` is valid for models such as XTTS when their manifest says the transcript is optional.
- Other cloning engines may require the exact reference transcript; add it to the profile rather than creating a model-bound duplicate profile.
- Check target-language support and cross-lingual cloning capability in the selected manifest.

## XTTS / Coqui environment issues

### XTTS does not appear available

Run:

```bat
install_xtts_worker.bat
```

The current implementation creates `.venv-xtts`. `run.bat` starts the same generic TTS host implementation under that environment on `127.0.0.1:8099`.

### Why is XTTS not installed into the main `.venv`?

The separation is deliberate dependency isolation. The primary runtime tracks a different Hugging Face Transformers lifecycle than Coqui/XTTS. Keeping them separate prevents dependency pinning or upgrades in one model family from destabilizing the other.

Do not fix an XTTS dependency problem by blindly installing Coqui packages into `.venv`.

### Port 8099 is unavailable

The current implementation uses fixed localhost ports:

```text
primary generic TTS host: 8098
XTTS generic TTS host:    8099
```

Check for an existing process using the port and make sure a prior VoxPassport worker was terminated cleanly.

This fixed-port arrangement is expected to be replaced eventually by supervisor-managed runtime profiles and dynamically assigned/discovered worker endpoints. Until that exists, port collisions are an operational constraint of the current launcher.

### XTTS host is running but model load fails

- Verify `.venv-xtts` was created successfully.
- Verify `runtime/workers/tts_host/requirements-xtts.txt` installed without dependency-resolution errors.
- Verify the XTTS checkpoint under `models/xtts-v2-romanian-v2/` is complete.
- Check `VOXPASSPORT_XTTS_MODEL_DIR` if using a non-default checkpoint location.
- Check CUDA/PyTorch availability from the `.venv-xtts` interpreter rather than from the main `.venv`.

### XTTS remains in VRAM after switching models

That is a bug. The orchestrator should unload the prior `ManifestTtsAdapter`, which in turn unloads the XTTS driver in the isolated host before the replacement model uses the shared GPU.

Check both host processes and `/metrics`. If XTTS remains allocated after a successful model switch, capture the model IDs and worker metrics and report it.

## Native Higgs issues

### Native Higgs DLL cannot load

- Verify `native/audiocpp_engine.dll` exists or set `VOXPASSPORT_HIGGS_NATIVE_DLL` to a compatible build.
- Verify the required CUDA runtime DLLs are discoverable through `CUDA_PATH`/`PATH`.
- Verify the DLL contains code compatible with the installed GPU architecture.
- Verify the Q4 model package exists under `models/higgs-tts-3-q4_k_m/`.

Native Higgs is still an ordinary worker-side `TtsDriver`; do not reintroduce a special application adapter to work around DLL loading problems.

## Model hot-swap issues

### Hot-swap stalls while loading a model

- Check VRAM availability.
- Confirm no previous heavyweight TTS worker still owns GPU memory.
- Allow committed speech to drain before assuming the swap is hung.
- Check the target worker's health/load response.

### Model fails health check after swap

- Keep the current known-good model active when possible.
- Verify the new model is fully downloaded.
- Check whether the failure is in manifest resolution, worker startup, driver load, or the underlying backend.

## Installation issues

### Model download fails

- Check network connectivity.
- Verify disk space at the configured model storage path.
- Retry resumable downloads where supported.
- Check whether the entry is intentionally watchlist-only and therefore has no downloadable upstream artifact configured.

## Session stability

### Memory grows over a long session

- Memory should not grow without bound; treat sustained growth as a bug.
- Check queue depths for unbounded accumulation.
- For XTTS, use `benchmarks/xtts_romanian_soak.py` to record CUDA allocated/reserved memory across alternating turns.
- Distinguish allocated memory from allocator-reserved memory before concluding a leak exists.

## Runtime Integrity

The repository's Runtime Integrity workflow compiles runtime/test sources and exercises routing, low-VRAM, XTTS helper, and TTS plugin architecture tests without downloading heavyweight model weights.

Useful local checks include:

```bat
.venv\Scripts\python.exe -m compileall -q runtime agents tests benchmarks scripts
.venv\Scripts\python.exe -m pytest -q tests/integration tests/test_tts_plugin_architecture.py tests/test_xtts_romanian.py
```

Hardware acceptance tests such as native Higgs or 50-turn XTTS soak testing still need to run on the target GPU.
