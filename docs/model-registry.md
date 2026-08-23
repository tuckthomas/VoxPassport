# VoxPassport Model Registry

## Overview

`ModelRegistry` is the persistent source of installation state, active capability slots, benchmark metadata, pinning, and known-good configurations. It is deliberately separate from model weight files and from model-specific runtime implementation code.

The registry does **not** own local TTS implementation details. Local TTS identity, aliases, capabilities, driver entrypoints, and runtime metadata originate in `runtime/tts_manifests/*.json` and are bridged into the registry at startup.

## Registry entry schema

A registry entry tracks fields such as:

```json
{
  "model_id": "nvidia-parakeet-tdt-0.6b-v3",
  "name": "NVIDIA Parakeet TDT 0.6B v3",
  "family": "parakeet",
  "provider": "nvidia",
  "capability": "ASR",
  "upstream_id": "nvidia/parakeet-tdt-0.6b-v3",
  "revision": "main",
  "supported_source_languages": ["en", "ro", "..."],
  "supported_target_languages": [],
  "supports_english": true,
  "supports_romanian": true,
  "streaming_support": true,
  "voice_cloning_support": false,
  "cross_lingual_voice_cloning": false,
  "required_runtime": "transformers",
  "min_runtime_version": "",
  "quantization_options": ["fp16", "bf16"],
  "estimated_download_size_gb": 1.2,
  "installed_size_gb": null,
  "expected_vram_tiers": {"fp16": "~3GB"},
  "expected_ram_gb": 2.0,
  "license": "CC-BY-4.0",
  "commercial_use": "yes",
  "redistribution": "yes",
  "local_benchmarks": {},
  "installation_status": "not_installed",
  "last_used": null,
  "last_benchmarked": null,
  "is_active": false,
  "is_pinned": false,
  "eligible_for_cleanup": true
}
```

The exact serialized fields can evolve, but the architectural split should remain: the registry stores cross-model lifecycle state; model-specific TTS declaration remains in manifests.

## Capability-based model selection

Application business logic should request active models by capability rather than branch on model names:

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
| ASR | Local/source language | `asr_en` or corresponding source slot |
| ASR | Remote/source language | `asr_ro` or corresponding source slot |
| Translation | EN → RO | `translation_en_ro` |
| Translation | RO → EN | `translation_ro_en` |
| TTS | Romanian output | `tts_ro` |
| TTS | English output | `tts_en` |
| VAD | Shared | `vad` |

Logical slots do not imply duplicate physical model instances. The current low-VRAM architecture can point both ASR directions to one shared Parakeet model, both translation directions to one MiLMMT model, and both TTS directions to one active TTS model.

## Local TTS registry ownership

Local TTS is special only in where its declaration originates—not in how it appears to the rest of the application.

```text
runtime/tts_manifests/*.json
          │
          ▼
manifest loader / registry bridge
          │
          ▼
ModelRegistry
          │
          ├── Model Settings / Model Hub metadata
          ├── active tts_en / tts_ro slots
          └── ManifestTtsAdapter construction
```

`ModelManagerController` must not maintain a second hard-coded alias table for local TTS models. Native Higgs is not separately registered by detection logic; it is an ordinary manifest-driven model whose driver knows how to use the native DLL/runtime.

## TTS runtime profiles and endpoints

Today, TTS manifests include enough worker endpoint information for the application to reach the current generic hosts:

```text
primary environment -> generic host :8098
XTTS environment    -> generic host :8099
```

That is current deployment metadata, not a fundamental property of the models.

The preferred future design is to add a `runtime_profile` concept and let a TTS runtime supervisor resolve the actual interpreter, environment, process, and endpoint. At that point the registry should continue to store the active **model ID**, not transient worker ports or process IDs.

Example future separation:

```text
Registry:  active TTS = xtts-v2-romanian-v2
Manifest:  runtime_profile = coqui-xtts
Supervisor: coqui-xtts currently running at ephemeral localhost endpoint X
```

This preserves stable model identity while allowing runtime topology to change independently.

## Hot-swap lifecycle

A conceptual swap is:

```text
REQUESTED
    ↓
RESOLVE MODEL / MANIFEST
    ↓
DRAIN COMMITTED WORK
    ↓
LOAD / HEALTH-CHECK TARGET
    ↓
SWITCH ACTIVE SLOT
    ↓
UNLOAD OLD MODEL WHEN NO LONGER SHARED
    ↓
ACTIVE
```

Important policies:

- A committed spoken utterance should not be interrupted by a routine model swap.
- If memory permits, compatible models may preload before activation.
- On constrained hardware, draining and unloading the old model before loading the new heavyweight model is safer than forcing simultaneous residency.
- A cross-host TTS switch must release the old worker-side model so an inactive process does not continue occupying VRAM.
- On failure, keep or restore the prior known-good model whenever possible.

## Known-good model sets

A known-good set captures model identities, not process topology. Example:

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

A future runtime supervisor should be free to launch those same model IDs under different compatible worker endpoints without invalidating the known-good set.

## Session stability policy

- Do not auto-replace models during an active conference call solely because a newly discovered model exists.
- A model discovered during a call should be staged for later evaluation.
- Automatic failover is appropriate only when the active model fails and a validated fallback exists.
- Voice profiles remain independent from the active TTS model.
- Transcript requirements are model capabilities and are not stored as a permanent property of the voice profile itself.
