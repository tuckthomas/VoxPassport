# VoxPassport Model Registry

## Overview

`ModelRegistry` is the persistent source of installation state, active capability slots, benchmark metadata, pinning, and known-good configurations. It is deliberately separate from model weight files and model-specific runtime implementation code.

For local TTS there are three distinct sources of truth:

- `runtime/tts_manifests/*.json` — stable **model** declaration;
- `runtime/tts_backend_runtimes/*.json` — reusable **backend server family** lifecycle declarations;
- `runtime/profiles/runtime_profiles.json` — dependency-compatible **environment families**.

The registry stores stable model lifecycle state. The TTS supervisor owns ephemeral worker/backend process and endpoint state.

## Registry entry schema

A registry entry tracks cross-model lifecycle metadata such as:

```json
{
  "model_id": "nvidia-parakeet-tdt-0.6b-v3",
  "name": "NVIDIA Parakeet TDT 0.6B v3",
  "family": "parakeet",
  "provider": "nvidia",
  "capability": "ASR",
  "upstream_id": "nvidia/parakeet-tdt-0.6b-v3",
  "revision": "main",
  "supports_english": true,
  "supports_romanian": true,
  "streaming_support": true,
  "required_runtime": "transformers",
  "installation_status": "not_installed",
  "is_active": false,
  "is_pinned": false
}
```

The registry stores model identity/lifecycle information. It does **not** persist ephemeral TTS ports, PIDs, backend processes, or deployment commands.

## Capability-based model selection

Application business logic requests active models by capability rather than branching on model names:

```python
registry.get_active_model(capability="ASR", language="en")
registry.get_active_model(capability="ASR", language="ro")
registry.get_active_model(capability="TRANSLATION", language_pair="en-ro")
registry.get_active_model(capability="TRANSLATION", language_pair="ro-en")
registry.get_active_model(capability="TTS", language="ro")
registry.get_active_model(capability="TTS", language="en")
registry.get_active_model(capability="VAD")
```

Logical slots do not imply duplicate physical weights. Both TTS slots may point to one active supervised TTS model.

## Local TTS ownership

```text
TTS model manifest
  model ID / aliases / capabilities
  driver + runtime_profile
  optional backend_runtime + backend_args
             │
             ├────────────► ModelRegistry
             │               install / active / benchmark state
             │
             ▼
      TtsRuntimeSupervisor
             │
             ├── worker runtime profile
             ├── optional BackendRuntimeCatalog entry
             ├── ephemeral worker/backend PIDs and ports
             └── health / residency / recovery
```

`ModelManagerController` must not maintain a second local-TTS alias catalog. Native Higgs, XTTS, MOSS, full Higgs, and VoxCPM are all ordinary model manifests.

## Backend runtimes are not models

A reusable backend runtime is deployment infrastructure, not a selectable model. It therefore does not receive its own model-registry entry.

Example:

```text
Registry model:    moss-tts-1.5
Model manifest:    runtime_profile = core
                   backend_runtime = moss-openai-server
                   backend_args.checkpoint = OpenMOSS-Team/...
Backend runtime:   runtime_profile = core
                   launch/health/remote family contract
Supervisor:        transient worker/backend PIDs + endpoints
```

A future `moss-tts-1.6` can point to the same `moss-openai-server` backend runtime with another checkpoint argument. No additional registry architecture, launcher environment variable, or supervisor branch is required.

## TTS runtime topology is not registry identity

For XTTS:

```text
Registry:    active TTS model = xtts-v2-romanian-v2
Manifest:    runtime_profile = coqui-xtts
Supervisor:  coqui-xtts worker = transient PID/endpoint
```

For a proxy-backed model:

```text
Registry:    active TTS model = moss-tts-1.5
Manifest:    backend_runtime = moss-openai-server
Supervisor:  transient generic worker + managed MOSS server
```

Therefore:

- active slots persist model IDs, never worker/backend ports;
- known-good sets persist model IDs, never process topology;
- one backend runtime can serve many model manifests over time;
- Model Settings obtains live worker/backend state from diagnostics;
- changing an ephemeral endpoint does not change model identity.

## Hot-swap lifecycle

For local TTS:

```text
requested model
      ↓
resolve model manifest
      ↓
resolve worker runtime profile
      ↓
resolve optional reusable backend runtime
      ↓
validate backend_args
      ↓
unload prior driver
      ↓
terminate prior managed backend if any
      ↓
terminate incompatible prior worker if needed
      ↓
launch/health-check target backend from reusable runtime definition
      ↓
start/reuse target worker
      ↓
inject ephemeral backend endpoint
      ↓
load + health-check target driver/model
      ↓
commit active model
```

Activation failure attempts rollback to the previous manifest/backend.

Important policies:

- same-profile models can reuse one generic worker process;
- a local proxy backend is part of supervised TTS residency;
- an alive-but-unhealthy backend is recycled before reuse;
- explicit non-loopback remote backend services are outside local GPU/process residency;
- unmanaged localhost backend services are rejected;
- a model on an existing backend family requires only another model manifest.

## Installation state versus runtime state

These remain separate:

```text
Model installed?
  -> model registry / checkpoint state

Worker runtime profile installed?
  -> runtime-profile catalog and diagnostics

Backend runtime family configured?
  -> BackendRuntimeCatalog definition + optional deployment override

Worker/backend process running?
  -> ephemeral TTS supervisor state
```

A model can be downloaded while a required dependency profile or backend-family deployment command is unavailable. Activation must fail clearly rather than creating model-specific fallback paths.

## Known-good model sets

Known-good sets capture model IDs, not backend/runtime process details:

```json
{
  "models": {
    "asr_en": "nvidia-parakeet-tdt-0.6b-v3",
    "asr_ro": "nvidia-parakeet-tdt-0.6b-v3",
    "translation_en_ro": "xiaomi-milmmt-46-1b-v1.0",
    "translation_ro_en": "xiaomi-milmmt-46-1b-v1.0",
    "tts_ro": "omnivoice-stock",
    "tts_en": "omnivoice-stock",
    "vad": "silero-vad-v6.2.1"
  }
}
```

The supervisor may recreate transient TTS processes/endpoints without invalidating a known-good set.

## Session stability policy

- Do not auto-replace models during an active call solely because a new model exists.
- Stage newly discovered candidates for later evaluation.
- Automatic recovery/failover is appropriate when the active runtime fails and a validated fallback exists.
- Voice profiles remain independent from the active TTS model.
- Reference-transcript requirements come from TTS capabilities, not permanent voice-profile schema.
