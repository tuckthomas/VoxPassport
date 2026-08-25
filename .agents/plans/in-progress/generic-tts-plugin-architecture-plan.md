# Generic TTS Plugin Architecture Plan

Status: Implementation and CI validation complete; environment/hardware acceptance remains

Purpose: Keep VoxPassport local TTS genuinely modular: one application adapter, one stable worker protocol, schema-driven model manifests, reusable backend-runtime definitions, dependency runtime profiles, worker-side drivers, and supervisor-owned local process topology.

## Application boundary

- [x] Define `voxpassport.tts.v1` with health, capabilities, load, unload, streamed speech, WAV output, and metrics.
- [x] Define the worker-side `TtsDriver` interface.
- [x] Make `ManifestTtsAdapter` the only local TTS application adapter.
- [x] Keep model/DLL/backend implementation details inside worker-side drivers.
- [x] Remove concrete OmniVoice/Higgs/MOSS/VoxCPM/XTTS application adapters.
- [x] Remove local-TTS model-name dispatch from the main daemon and orchestrator.

## Model declarations

- [x] Make `runtime/tts_manifests/*.json` the sole built-in local-TTS model catalog.
- [x] Upgrade current model manifests to schema v3.
- [x] Keep model identity, aliases, capabilities, driver settings, worker `runtime_profile`, optional `backend_runtime`, and model-specific `backend_args` in model manifests.
- [x] Reject worker URLs, fixed local ports, `backend_process`, `backend_url`, and `backend_url_env` from model manifests.
- [x] Make runtime capability discovery authoritative after model load.

## Reusable backend runtimes

The former per-model `backend_process.command_env` design has been replaced. See `.agents/plans/completed/tts-backend-runtime-catalog-plan.md`.

- [x] Add `BackendRuntime` / `BackendRuntimeCatalog`.
- [x] Store reusable backend server lifecycle definitions under `runtime/tts_backend_runtimes/`.
- [x] Give current full Higgs, MOSS, and VoxCPM proxy families stable backend runtime IDs.
- [x] Move family launch/health/remote lifecycle metadata out of individual model manifests.
- [x] Validate required/unknown `backend_args` before activation.
- [x] Allow one backend runtime to serve multiple model manifests with different checkpoint arguments.
- [x] Keep family-level command overrides deployment configuration rather than per-model integration requirements.
- [x] Keep explicit non-loopback remote URLs as family-level backend runtime overrides.
- [x] Reject unmanaged loopback proxy backends.

## Runtime profiles and supervision

See `.agents/plans/in-progress/tts-runtime-profile-supervisor-plan.md`.

- [x] Group dependency-compatible models/backends into runtime profiles rather than one environment per model.
- [x] Define `core` and isolated `coqui-xtts` profiles.
- [x] Let model worker and backend runtime select profiles independently.
- [x] Add `TtsRuntimeSupervisor` for dynamic worker/backend ports, health, load/unload, residency, rollback, recovery, and idle shutdown.
- [x] Make `run.bat` start the integrated runtime plus canonical Expo web client without prestarting model-specific TTS workers/backends.
- [x] Make `ManifestTtsAdapter.load()` a cheap logical activation.
- [x] Keep one active supervised local TTS model by default on low-VRAM hardware.
- [x] Terminate managed backend process trees on model replacement/release.
- [x] Recycle an alive-but-unhealthy managed backend before reuse.
- [x] Retry a crashed worker only when failure occurs before first audio.
- [x] Keep backend-runtime deployment metadata supervisor-side; generic workers receive only ephemeral endpoint overrides.

## Driver migrations

- [x] Migrate OmniVoice to `OmniVoiceDriver`.
- [x] Migrate native Higgs/audiocpp Q4 to `HiggsNativeDriver`.
- [x] Use reusable `OpenAiSpeechProxyDriver` for full Higgs, MOSS, and VoxCPM.
- [x] Migrate XTTS Romanian to `XttsRomanianDriver` plus worker-side runtime/helpers.
- [x] Preserve XTTS Romanian normalization, streaming, conditioning cache, metrics, and hybrid conditioning.

## Voice-profile behavior

- [x] Keep canonical voice profiles model-independent.
- [x] Keep `reference.txt` optional unless the selected manifest requires it.
- [x] Drive transcript validation from manifest capabilities.
- [x] Keep optional target-language conditioning separate from canonical `reference.wav`.

## Registry and UI

- [x] Bridge model manifest metadata into the existing registry without a second hard-coded TTS catalog.
- [x] Keep backend runtimes as deployment metadata rather than registry model identities.
- [x] Keep canonical Expo UI routing model-agnostic.
- [x] Report worker and managed-backend state through runtime diagnostics.
- [x] Show the active runtime broken when either supervised layer exits or becomes unreachable.

## Validation

- [x] Test manifest schema/alias/driver loading.
- [x] Test backend-runtime schema/argument validation.
- [x] Test every local TTS model uses `ManifestTtsAdapter`.
- [x] Test full Higgs/MOSS/VoxCPM share the reusable proxy driver.
- [x] Test synthetic model manifests route without daemon model-name branches.
- [x] Test two different model manifests hot-swap through one reusable backend runtime with different checkpoint arguments.
- [x] Test dynamic worker/backend ports, same-profile worker reuse, cross-profile termination, managed-backend termination, idle shutdown, rollback, and crash recovery.
- [x] Add source integrity checks preventing fixed TTS ports and model-specific supervisor branches.
- [x] Add backend-runtime tests to Runtime Integrity CI.
- [x] Observe Runtime Integrity green after the architecture migration and during the final Expo/native-audio branch validation.

## Environment / hardware acceptance

- [ ] Generate and commit `runtime/profiles/coqui-xtts/uv.lock` from a connected environment and verify Windows/CUDA sync.
- [ ] Verify real RTX 2070 VRAM release across XTTS/native-Higgs/OmniVoice/proxy-backed model switches.
- [ ] Complete the XTTS Romanian voice-quality/soak acceptance items in the dedicated XTTS plan.

## Current architectural rule

```text
New model on an existing supported backend family
    -> model manifest only

New dependency family
    -> runtime profile

New backend server implementation
    -> one reusable backend runtime definition

New inference/protocol semantics
    -> one reusable worker-side driver if needed

New application adapter / daemon branch / supervisor model-name branch
    -> almost never
```

No backwards-compatibility layer is intentionally retained for the deleted local-TTS adapter/fixed-port/per-model-backend architecture. This plan remains in-progress only for the explicitly listed environment/hardware acceptance items.
