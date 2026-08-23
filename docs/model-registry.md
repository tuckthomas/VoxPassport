# VoxPassport Model Registry

## Overview

`ModelRegistry` is the persistent source of installation state, active capability slots, benchmark metadata, pinning, and known-good configurations. It is deliberately separate from model weight files and model-specific runtime implementation code.

For local TTS, model declaration originates in `runtime/tts_manifests/*.json`. The registry stores stable model lifecycle state; the TTS runtime supervisor owns ephemeral worker/backend process and endpoint state.

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
  "voice_cloning_support": false,
  "required_runtime": "transformers",
  "estimated_download_size_gb": 1.2,
  "expected_vram_tiers": {"fp16": "~3GB"},
  "installation_status": "not_installed",
  "is_active": false,
  "is_pinned": false
}
```

The exact serialized fields can evolve, but the architectural split should remain: the registry stores stable model lifecycle information, while local TTS driver/profile/backend-lifecycle declaration remains in manifests.

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

## Per-direction active slots

| Capability | Direction | Runtime slot |
| --- | --- | --- |
| ASR | Local/source | `asr_en` or corresponding source slot |
| ASR | Remote/source | `asr_ro` or corresponding source slot |
| Translation | EN → RO | `translation_en_ro` |
| Translation | RO → EN | `translation_ro_en` |
| TTS | Romanian output | `tts_ro` |
| TTS | English output | `tts_en` |
| VAD | Shared | `vad` |

Logical slots do not imply duplicate physical weights. Both TTS slots may point to one active supervised TTS model.

## Local TTS ownership

```text
runtime/tts_manifests/*.json
          │
          ├── stable model ID / aliases
          ├── capabilities
          ├── driver declaration
          ├── runtime_profile
          └── optional backend_process contract
                    │
                    ├──────────────► TTS Runtime Supervisor
                    │                worker/backend process,
                    │                dynamic endpoints, residency
                    │
                    ▼
             registry bridge
                    │
                    ▼
               ModelRegistry
                    │
                    ├── installation state
                    ├── active tts_en / tts_ro slots
                    ├── pinning / cleanup state
                    └── benchmark / known-good state
```

`ModelManagerController` must not maintain a second local-TTS alias catalog. Native Higgs is an ordinary manifest-driven model; XTTS is an ordinary manifest-driven model assigned to a different dependency profile; proxy models remain ordinary manifests whose local backend lifecycle is supervised when required.

## TTS runtime topology is not registry identity

Examples:

```text
Registry:    active TTS model = xtts-v2-romanian-v2
Manifest:    runtime_profile = coqui-xtts
Supervisor:  coqui-xtts worker = PID/ephemeral endpoint at this moment
```

For a local proxy model:

```text
Registry:    active TTS model = moss-tts-1.5
Manifest:    runtime_profile = core
             backend_process = supervisor launch contract
Supervisor:  core worker + MOSS backend = transient PIDs/endpoints
```

Only the model ID and manifest declaration are stable configuration. Worker/backend PIDs and localhost ports are transient runtime state.

Therefore:

- registry active slots persist **model IDs**, not worker or backend ports;
- known-good sets persist model IDs, not process topology;
- the same model may run at different ephemeral endpoints after restart;
- Model Settings obtains live worker/backend health from resource diagnostics rather than persisting it into registry identity.

## Hot-swap lifecycle

For local TTS the implemented lifecycle is:

```text
REQUESTED MODEL
      ↓
resolve manifest + runtime_profile
      ↓
if needed, drain current committed utterance
      ↓
unload old worker-side driver
      ↓
terminate old managed backend process tree, if any
      ↓
terminate old worker if profile-incompatible
      ↓
start/health-check target managed backend, if any
      ↓
start/reuse target profile worker
      ↓
inject dynamic backend endpoint when required
      ↓
load + health-check target driver/model
      ↓
activate target model
      ↓
rollback prior manifest/backend on activation failure when possible
```

Important policies:

- a committed utterance is not interrupted by a routine same-host swap;
- same-profile models can reuse one generic worker process;
- a managed local proxy backend is terminated whenever its model is released or replaced;
- cross-profile TTS changes also terminate the incompatible old generic worker;
- on constrained hardware, avoiding simultaneous heavyweight local TTS residency is the default;
- an alive-but-unhealthy managed backend is recycled before synthesis;
- worker/backend crashes do not change stable model identity; the supervisor recreates transient processes when recovery is appropriate;
- explicit non-loopback proxy URLs are remote resources and therefore outside local GPU/process residency.

## Installation state versus runtime state

These are separate questions:

```text
Model installed?
  -> checkpoint/package state tracked by the model registry

Runtime profile installed?
  -> interpreter/dependency environment tracked by runtime-profile diagnostics

Generic worker running?
  -> ephemeral supervisor process state

Managed local proxy backend running?
  -> ephemeral supervisor backend state, when required by the active model
```

A model can therefore be downloaded while its required runtime profile or local backend launch command is unavailable. Activation should fail clearly until those runtime requirements are satisfied.

## Known-good model sets

A known-good set captures model identities, not process topology:

```json
{
  "set_id": "kgms-example",
  "app_version": "0.1.0",
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

The supervisor is free to recreate those models under new ephemeral worker/backend endpoints without invalidating the set.

## Session stability policy

- Do not auto-replace models during an active call solely because a new model exists.
- Stage newly discovered candidates for later evaluation.
- Automatic recovery/failover is appropriate when the active runtime fails and a validated fallback exists.
- Voice profiles remain independent from the active TTS model.
- Reference-transcript requirements come from TTS capabilities, not from permanent voice-profile schema.
