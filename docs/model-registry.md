# Model Registry — LiveTranslator

## Overview

The `ModelRegistry` is a persistent, versioned database of all known, installed, and active models. It is independent of model weight files and survives application upgrades.

## Registry Entry Schema

Every registry entry contains:

```json
{
  "model_id": "nvidia-nemotron-3.5-asr-streaming-0.6b",
  "name": "NVIDIA Nemotron 3.5 ASR Streaming 0.6B",
  "family": "nemotron",
  "provider": "nvidia",
  "capability": "ASR",
  "upstream_id": "nvidia/nemotron-asr-...",
  "revision": "main",
  "supported_source_languages": ["en", "ro", "..."],
  "supported_target_languages": null,
  "supports_english": true,
  "supports_romanian": true,
  "streaming_support": true,
  "voice_cloning_support": false,
  "cross_lingual_voice_cloning": false,
  "required_runtime": "nemo",
  "min_runtime_version": "2.0.0",
  "quantization_options": ["fp16", "bf16", "int8"],
  "estimated_download_size_gb": 1.2,
  "installed_size_gb": null,
  "expected_vram_tiers": {"fp16": "~3GB", "int8": "~1.5GB"},
  "expected_ram_gb": 2.0,
  "license": "OpenMDW-1.1",
  "commercial_use": "verify",
  "redistribution": "verify",
  "upstream_benchmarks": {},
  "local_benchmarks": {},
  "installation_status": "not_installed",
  "last_used": null,
  "last_benchmarked": null,
  "is_active": false,
  "is_pinned": false,
  "eligible_for_cleanup": true
}
```

## Capability-Based Model Selection

The application never references model names in business logic. It requests by capability:

```python
registry.get_active_model(capability="ASR", language_pair="en-ro")
registry.get_active_model(capability="TRANSLATION", language_pair="en-ro")
registry.get_active_model(capability="TRANSLATION", language_pair="ro-en")
registry.get_active_model(capability="TTS", language="ro")
registry.get_active_model(capability="TTS", language="en")
registry.get_active_model(capability="VAD")
```

## Per-Direction Active Models

Different models can be active for each direction:

| Capability | Direction | Config Key |
|-----------|-----------|------------|
| ASR | English → (outbound) | `models.asr.en` |
| ASR | Romanian → (inbound) | `models.asr.ro` |
| Translation | EN → RO | `models.translation.en_ro` |
| Translation | RO → EN | `models.translation.ro_en` |
| TTS | Romanian output | `models.tts.ro` |
| TTS | English output | `models.tts.en` |
| VAD | Both directions | `models.vad` |

## Hot-Swap Lifecycle

```
REQUESTED → PRELOADING → READY → DRAINING_OLD_MODEL → ACTIVE
                                                      ↓
                                                   FAILED → ROLLED_BACK
```

- A model swap never interrupts a committed spoken utterance.
- If VRAM permits, new model preloads before old model unloads.
- If VRAM does not permit: Pause stage → Drain → Unload old → Load new → Health check → Resume.
- On failure: Restore last known-good model automatically.

## Known-Good Model Sets

A `KnownGoodModelSet` is persisted after every successful validation:

```json
{
  "set_id": "kgms-2026-08-17-001",
  "validated_at": "2026-08-17T00:00:00Z",
  "app_version": "0.1.0",
  "models": {
    "asr_en": "nvidia-nemotron-3.5-asr-streaming-0.6b",
    "asr_ro": "nvidia-nemotron-3.5-asr-streaming-0.6b",
    "translation_en_ro": "xiaomi-milmmt-46-1b-v1.0",
    "translation_ro_en": "xiaomi-milmmt-46-1b-v1.0",
    "tts_ro": "omnivoice-stock",
    "tts_en": "omnivoice-stock",
    "vad": "silero-vad"
  }
}
```

One-click rollback to the previous known-good set is always available.

## Session Stability Policy

- Do not auto-replace models during an active conference call.
- A model discovered during a call is staged for later use only.
- Automatic failover is permitted only if the active model crashes and a known-good fallback exists.
