# VoxPassport Model Registry

## Overview

`ModelRegistry` is the persistent source of model lifecycle state: installation status, active capability slots, benchmark metadata, pinning, cleanup eligibility, trust/recommendation state, and known-good configurations. It is deliberately separate from model weight files, UI state, and ephemeral runtime processes.

The canonical Expo Models & Engines screen consumes typed runtime/model-manager APIs. It does not maintain a second catalog, infer installability from model names, or mutate legacy global arrays.

## Sources of truth

For general model lifecycle:

```text
ModelRegistry
  -> install state
  -> active model IDs
  -> pinning / cleanup eligibility
  -> known-good sets
  -> benchmark/recommendation metadata
```

For local TTS there are additional declarative owners:

- `runtime/tts_manifests/*.json` — stable **model** declarations;
- `runtime/tts_backend_runtimes/*.json` — reusable **backend server family** lifecycle declarations;
- `runtime/profiles/runtime_profiles.json` — dependency-compatible **environment families**.

The TTS supervisor owns ephemeral worker/backend process state. None of that ephemeral topology becomes model identity.

## Registry entry schema

A registry entry tracks lifecycle/capability metadata such as:

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
  "installation_status": "not_installed",
  "is_active": false,
  "is_pinned": false
}
```

The API enriches registry entries with installation-action metadata:

```json
{
  "installable": true,
  "installation_reason": null
}
```

or, when an action is unavailable:

```json
{
  "installable": false,
  "installation_reason": "No verified official downloadable repository is configured for this catalog entry."
}
```

This ownership is intentional. The Expo client renders the backend decision instead of creating model-name exceptions.

## Installation state versus adapter support

A model being downloaded does not automatically mean VoxPassport has a production runtime adapter for that model family.

These are separate questions:

```text
Can the model package be installed?
    -> registry/model-manager installer metadata

Can the selected capability activate this model?
    -> runtime adapter/manifest implementation
```

Activation must fail explicitly when an installed model lacks an implemented production adapter rather than silently routing through a different model.

## Capability-based selection

Application business logic requests active models by capability instead of branching on model names:

```python
registry.get_active_model(capability="ASR", language="en")
registry.get_active_model(capability="ASR", language="ro")
registry.get_active_model(capability="TRANSLATION", language_pair="en-ro")
registry.get_active_model(capability="TRANSLATION", language_pair="ro-en")
registry.get_active_model(capability="TTS", language="ro")
registry.get_active_model(capability="TTS", language="en")
registry.get_active_model(capability="VAD")
```

Logical slots do not imply duplicate model weights. Multiple directions/slots can point to one physical active model instance.

## Expo model workflows

The canonical client uses typed APIs for:

- available/installed model listing;
- install requests;
- progress polling;
- activation;
- uninstall;
- pipeline enable/disable where supported;
- model-storage settings;
- remote endpoint configuration.

The client must not:

- infer installability from `upstream_id` itself;
- rewrite canonical model IDs with UI-only patches;
- assume an install implies runtime adapter support;
- start Python/CUDA workers directly.

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

Local TTS aliases originate from manifests/catalog integration. The model manager must not grow a parallel hard-coded TTS catalog merely to satisfy UI naming.

## Backend runtimes are not models

A reusable backend runtime is deployment infrastructure, not a selectable model and therefore does not get its own model-registry entry.

Example:

```text
Registry model:    moss-tts-1.5
Model manifest:    runtime_profile = core
                   backend_runtime = moss-openai-server
                   backend_args.checkpoint = OpenMOSS-Team/...
Backend runtime:   reusable launch/health/runtime-family contract
Supervisor:        transient worker/backend PID + endpoint
```

A future checkpoint on the same backend family should normally require another model manifest, not new application routing.

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
Supervisor:  transient generic worker + managed MOSS backend
```

Therefore:

- active slots persist model IDs, never worker/backend ports;
- known-good sets persist model IDs, never process topology;
- a backend runtime can serve multiple model manifests over time;
- runtime diagnostics expose live process/backend health;
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
resolve optional backend runtime
      ↓
validate backend_args
      ↓
unload prior driver
      ↓
terminate prior managed backend if needed
      ↓
terminate incompatible worker if needed
      ↓
launch/health-check target backend
      ↓
start/reuse target worker
      ↓
inject ephemeral backend endpoint
      ↓
load + health-check target model/driver
      ↓
commit active registry state
```

Activation is transactional: failure attempts to preserve/restore the previous active configuration.

## Installation/runtime-state separation

```text
Model installed?
  -> ModelRegistry / model store

Worker runtime profile installed?
  -> runtime-profile catalog/diagnostics

Backend runtime configured?
  -> BackendRuntimeCatalog + deployment configuration

Worker/backend process running?
  -> ephemeral TTS supervisor state
```

A downloaded model can legitimately remain inactive if its dependency profile, backend family, or runtime adapter is unavailable.

## Known-good sets

Known-good sets store stable model IDs, not ephemeral runtime topology:

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

## Session-stability policy

- Do not auto-replace models during an active call merely because a new candidate exists.
- Stage discovered candidates for explicit evaluation.
- Recovery/failover is appropriate when the active runtime fails and a validated fallback exists.
- Voice profiles remain independent from the active TTS model.
- Transcript requirements come from the selected TTS capability/manifest, not from a universal voice-profile schema.
- Strategy/routing mutation is blocked while an active native live-translation session owns the media path.
