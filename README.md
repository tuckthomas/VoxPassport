<div align="center">

<img src="apps/desktop-companion/assets/VoxPassport_icon_256.png" alt="VoxPassport icon" width="160" />

# VoxPassport
### Local-First Live Translation, Captions, Voice Cloning & Text-to-Speech

<p>
  A local-first platform for live speech translation with synchronized captions, speech-to-text, text translation, voice cloning, synthesized speech, and live conversation workflows.
</p>

<p>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python_3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12" /></a>
  <a href="https://pytorch.org/"><img src="https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white" alt="PyTorch" /></a>
  <a href="https://huggingface.co/"><img src="https://img.shields.io/badge/Hugging_Face-FFD21E?style=for-the-badge&logo=huggingface&logoColor=000" alt="Hugging Face" /></a>
  <a href="https://github.com/huggingface/transformers"><img src="https://img.shields.io/badge/Transformers-FFCC4D?style=for-the-badge&logo=huggingface&logoColor=000" alt="Transformers" /></a>
  <a href="https://developer.nvidia.com/cuda-zone"><img src="https://img.shields.io/badge/NVIDIA_CUDA-76B900?style=for-the-badge&logo=nvidia&logoColor=white" alt="NVIDIA CUDA" /></a>
</p>

</div>

---

## Project Overview

**VoxPassport** is a modular local-first audio and language platform for live multilingual conversation and standalone speech workflows. It can capture speech, detect voice activity, transcribe, translate, synthesize translated speech, route that audio to the correct listener/conference input, and publish synchronized captions. No single workflow requires every capability to be enabled.

VoxPassport began as a way to support natural conversations with family members in Romania despite a language barrier. English ↔ Romanian remains the primary development and benchmark pair, but the runtime is language-pair driven; actual language support is determined by the selected ASR, translation, and TTS models.

Voice identity is treated as a first-class capability. A saved voice profile is model-independent and can be consumed by any compatible cloning-capable TTS model.

## Product Interface

<table>
  <tr>
    <td width="50%"><img src="docs/images/translator-studio-live.png" alt="VoxPassport Live Translator Studio" /></td>
    <td width="50%"><img src="docs/images/voice-profile-studio.png" alt="VoxPassport Voice Profile Studio" /></td>
  </tr>
  <tr>
    <td align="center"><strong>Live Translator Studio</strong><br />Full-duplex speech, captions, and cloned-audio monitoring.</td>
    <td align="center"><strong>Voice Profile Studio</strong><br />Reference recording, enrollment, and cross-lingual preview.</td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/model-settings-active-engines.png" alt="VoxPassport active inference engines" /></td>
    <td width="50%"><img src="docs/images/model-hub.png" alt="VoxPassport Hugging Face model hub" /></td>
  </tr>
  <tr>
    <td align="center"><strong>Active Inference Engines</strong><br />Hot-swappable TTS, ASR, translation, and VAD slots.</td>
    <td align="center"><strong>Model Discovery Hub</strong><br />Hardware-aware model discovery, licensing, and installation.</td>
  </tr>
</table>

---

# Key Features

## Full-Duplex Multilingual Translation

```text
Local Microphone                         Remote Conference Audio
      │                                           │
      ▼                                           ▼
     VAD                                         VAD
      │                                           │
      ▼                                           ▼
     ASR                                         ASR
      │                                           │
      ▼                                           ▼
 Translation                                  Translation
      │                                           │
      ▼                                           ▼
 TTS / Voice Clone                           TTS / Voice Clone
      │                                           │
      ▼                                           ▼
Virtual Microphone                           Local Monitor
```

Both directions maintain independent language/routing state while physical model instances can be shared. The low-VRAM design can share one Parakeet ASR model, one MiLMMT translation model, and one active TTS model across both directions.

## Engine-Independent Voice Profiles

```text
Reference recording
+ optional exact transcript
              ↓
      Universal voice profile
              ↓
   Active cloning-capable TTS
              ↓
Translated or supplied target text
              ↓
Speech in the enrolled speaker's voice
```

The transcript is optional unless the selected TTS manifest declares that its cloning method requires one. Model-specific conditioning is derived from the canonical profile and does not replace the saved source recording.

## Truly Hot-Swappable Local TTS

Every local TTS model uses the same application boundary:

```text
Main VoxPassport runtime
        │
        ▼
ManifestTtsAdapter
        │
        ▼
TTS Runtime Supervisor
        │
        ├── Generic TTS worker (ephemeral localhost endpoint)
        │          │ voxpassport.tts.v1
        │          ▼
        │       TtsDriver
        │
        └── Optional reusable BackendRuntime
                   │
                   ▼
              managed backend process
              (ephemeral localhost endpoint)
```

Current local model manifests include OmniVoice, full Higgs TTS 3, native Higgs Q4_K_M, MOSS-TTS v1.5, VoxCPM2, and XTTS-v2 Romanian v2.

The model manifest does **not** own worker/backend ports or launch commands. A model that needs an external local server references a reusable backend runtime definition. For example:

```json
{
  "schema_version": 3,
  "model_id": "moss-tts-1.5",
  "runtime_profile": "core",
  "backend_runtime": "moss-openai-server",
  "backend_args": {
    "checkpoint": "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"
  }
}
```

The intended integration rule is:

```text
New model on an existing backend family
    -> model manifest only

New dependency family
    -> runtime profile

New backend server implementation
    -> one reusable backend runtime definition

New protocol semantics
    -> one reusable TtsDriver if necessary

New application/supervisor routing code
    -> almost never
```

That means adding another MOSS-compatible checkpoint does **not** require another model-specific command variable, local port, adapter, or supervisor branch.

See [`docs/tts-plugin-architecture.md`](docs/tts-plugin-architecture.md).

## Backend Runtime Families

Reusable backend server definitions live under `runtime/tts_backend_runtimes/`. They own family-level lifecycle details such as:

- backend dependency/runtime profile;
- reusable launch command template or one deployment-level family override;
- required/optional model arguments;
- health endpoint and startup timeout;
- endpoint injection option;
- optional explicit non-loopback remote service override.

Current proxy families are:

- `higgs-openai-server`;
- `moss-openai-server`;
- `voxcpm-openai-server`.

A backend-family command override is configured once for that server implementation, not once for every model using it.

## Supervisor-Managed Runtime Profiles

A runtime profile is a dependency-compatible environment family:

| Profile | Environment | Purpose |
| :--- | :--- | :--- |
| `core` | primary `.venv` | drivers/backends compatible with the main Python stack |
| `coqui-xtts` | `runtime/profiles/coqui-xtts/.venv` | Coqui/XTTS dependency family |

A backend runtime can select its own runtime profile independently from the generic worker model. This prevents a future server family's dependencies from contaminating the worker or another model family.

The supervisor:

- resolves worker and backend runtime profiles;
- starts processes only when needed;
- assigns available localhost ports dynamically;
- builds reusable backend commands from the family definition plus model `backend_args`;
- health-checks workers and managed backends;
- injects ephemeral endpoints into drivers at runtime;
- owns local TTS residency;
- reuses compatible workers;
- unloads/replaces models transactionally;
- recycles crashed or alive-but-unhealthy processes;
- shuts released idle workers down.

An explicit **non-loopback remote backend URL** is valid because it cannot occupy the local GPU. An unmanaged localhost backend is rejected.

XTTS remains isolated because the primary runtime and Coqui have different dependency constraints. That isolation is a dependency boundary, not another application architecture.

## True On-Demand TTS

`run.bat` starts only the main VoxPassport daemon. It does not prestart TTS workers or proxy backends.

`ManifestTtsAdapter.load()` is a cheap logical activation. Physical TTS processes are created only for explicit activation health validation or actual synthesis. A `CAPTIONS_ONLY` session therefore pays no TTS process overhead.

## Model Hub and Hot-Swappable Stack

Capability slots include:

- **VAD** — speech / non-speech detection
- **ASR** — automatic speech recognition
- **Translation / NMT** — text-to-text translation
- **Direct Speech Translation** — experimental speech-to-translated-text paths
- **TTS** — speech synthesis and voice cloning
- **Diarization** — optional speaker clustering for inbound multi-speaker audio

Local TTS metadata is sourced from TTS manifests and bridged into the registry; backend runtime definitions remain deployment metadata rather than separate models.

## Speaker Diarization

NVIDIA Streaming Sortformer can run as a parallel inbound diarization sidecar. It does not block ASR. Speaker labels represent anonymous clusters, not verified real-world identities.

## Live Captions and Conference Integration

Caption events are published over a localhost WebSocket service. The repository includes a desktop overlay and Chrome Manifest V3 companion currently targeted at Google Meet, while the core inference/audio-routing architecture remains conferencing-platform agnostic.

---

# Current Reference Stack

| Capability | Current Reference / Default | Alternatives & Research Paths | Notes |
| :--- | :--- | :--- | :--- |
| **VAD** | Silero VAD v6.2.1 | Future VAD adapters | Lightweight runtime model |
| **ASR** | NVIDIA Parakeet TDT 0.6B v3 | Meta OmniASR; NVIDIA Canary | One physical model can serve both directions |
| **Translation** | Xiaomi MiLMMT-46 1B v1.0 | MiLMMT 4B; Riva Translate; watchlist models | CPU placement is useful on low-VRAM systems |
| **TTS / Voice Cloning** | OmniVoice reference integration | native/full Higgs, MOSS, VoxCPM, XTTS Romanian | Model manifests + reusable backend runtimes + runtime profiles + `voxpassport.tts.v1` |
| **Direct Speech Translation** | Experimental | NVIDIA Canary-1B-v2 | Benchmark before replacing ASR → NMT |
| **Diarization** | Optional | NVIDIA Streaming Sortformer 4-Speaker v2.1 | Parallel inbound sidecar |

---

# Low-VRAM Runtime Policy

On constrained GPUs VoxPassport prioritizes controlled residency over keeping every model simultaneously loaded:

- both directions can share one physical Parakeet model;
- MiLMMT can run on CPU;
- optional Sortformer can remain on CPU;
- heavyweight ASR and local TTS generation are coordinated rather than intentionally competing for CUDA execution;
- audio capture and VAD continue while heavyweight GPU work runs;
- only one supervised local TTS model is active across runtime profiles by default;
- managed local proxy backends are terminated whenever their model is released or replaced, including same-profile switches;
- cross-profile TTS switches terminate the incompatible prior generic worker before loading the replacement;
- native Higgs runtime memory is treated as more than its GGUF file size because caches, activations, CUDA workspaces, and scratch buffers also consume VRAM.

Higher-memory systems can adopt more aggressive residency after it is measured safe.

---

# Operating Modes

| Mode | Description |
| :--- | :--- |
| `FULL_DUPLEX` | Both translation directions run simultaneously. |
| `OUTBOUND_TRANSLATION` | Local microphone → ASR → translation → captions/TTS → virtual microphone. |
| `INBOUND_TRANSLATION` | Conference audio → ASR → translation → captions/TTS → local monitor. |
| `CAPTIONS_ONLY` | ASR + translation + captions without TTS processes. |
| `TTS_NO_CLONE` | Use the active TTS engine without an enrolled cloned voice. |
| `TTS_CLONED` | Use the active voice profile with a cloning-capable TTS engine. |

---

# Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                    Main VoxPassport Runtime                  │
│ VAD → ASR → Translation → ManifestTtsAdapter → Audio Output │
└──────────────┬───────────────────────────────────────────────┘
               │ logical TTS model request
               ▼
┌──────────────────────────────────────────────────────────────┐
│                   TTS Runtime Supervisor                     │
│ manifest + runtime profiles + backend runtime catalog       │
└──────────────┬───────────────────────────┬───────────────────┘
               │ voxpassport.tts.v1        │ reusable backend runtime
               ▼                           ▼
┌──────────────────────────────┐   ┌───────────────────────────┐
│ Generic TTS Worker Host      │   │ Managed Proxy Backend     │
│ manifest → TtsDriver         │──►│ dynamic local port        │
└──────────────────────────────┘   └───────────────────────────┘
```

See [`docs/architecture.md`](docs/architecture.md) for the full runtime architecture.

---

# Repository Structure

```text
VoxPassport/
├── apps/
│   ├── browser-extension/
│   └── desktop-companion/
├── runtime/
│   ├── inference/
│   │   ├── adapters/
│   │   ├── model_registry/
│   │   ├── pipeline/
│   │   ├── server/
│   │   └── tts_plugins/                 # manifests/backend/runtime supervision
│   ├── profiles/
│   │   ├── runtime_profiles.json
│   │   └── coqui-xtts/pyproject.toml
│   ├── tts_backend_runtimes/             # reusable local/remote server families
│   ├── tts_manifests/                    # model declarations
│   └── workers/tts_host/                 # generic protocol host + TTS drivers
├── .agents/plans/
│   ├── pending/
│   ├── in-progress/
│   └── completed/
├── benchmarks/
├── tests/
├── scripts/
├── docs/
├── install.bat
└── run.bat
```

---

# Installation

## System Requirements

There is intentionally no single VRAM number that defines VoxPassport. Requirements depend on the models and modes selected.

| Resource | Practical Guidance |
| :--- | :--- |
| **Operating System** | Windows 10/11 is the current primary development target. |
| **Python** | Python 3.12. |
| **GPU** | NVIDIA CUDA GPU strongly recommended for real-time local speech inference. |
| **VRAM** | ~8 GB can run the lightweight/reference stack with low-VRAM policy; larger models may require more memory or more aggressive swapping. |
| **RAM** | Additional RAM is useful when translation/diarization are CPU-resident. |
| **Storage** | Model-dependent; checkpoints range from small VAD assets to multi-GB speech models. |
| **Audio Routing** | A virtual audio input/device is required to inject translated speech into a conference. |
| **FFmpeg** | Required for imported voice-profile normalization. |

## 1. Clone

```bash
git clone https://github.com/tuckthomas/VoxPassport.git
cd VoxPassport
```

## 2. Install the primary runtime

```bat
install.bat
```

This creates `.venv` and installs the primary inference/runtime dependencies.

## 3. Optional: provision XTTS/Coqui

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
```

To rebuild a damaged profile:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

When `uv` is available, `coqui-xtts` is synchronized as an independent project from `runtime/profiles/coqui-xtts/pyproject.toml`, producing its own `.venv` and `uv.lock`. When uv is unavailable, the manager uses the declared venv/pip fallback.

## 4. Start VoxPassport

```bat
run.bat
```

Or:

```bat
.venv\Scripts\python.exe runtime\inference\server\main.py
```

Persistent local services include:

| Service | Address | Purpose |
| :--- | :--- | :--- |
| **Studio / Model Manager** | `http://127.0.0.1:8766/manager/index.html` | Voice profiles, models, Live Studio, diagnostics |
| **Local API** | `http://127.0.0.1:8766` | Runtime/model/voice endpoints |
| **Caption WebSocket** | `ws://127.0.0.1:8765/ws/captions` | Live caption and translation events |

TTS worker/backend endpoints are intentionally not listed because they are ephemeral.

### Proxy TTS backend-family configuration

Full Higgs, MOSS, and VoxCPM currently use reusable OpenAI-style backend runtime families. Their deployment-level command overrides are:

```text
VOXPASSPORT_TTS_BACKEND_HIGGS_COMMAND
VOXPASSPORT_TTS_BACKEND_MOSS_COMMAND
VOXPASSPORT_TTS_BACKEND_VOXCPM_COMMAND
```

These variables configure a **backend server family once**. They are not model-specific integration requirements. A second model/checkpoint using the same backend runtime needs only another model manifest with different `backend_args`.

The corresponding family remote URL overrides are:

```text
VOXPASSPORT_TTS_BACKEND_HIGGS_URL
VOXPASSPORT_TTS_BACKEND_MOSS_URL
VOXPASSPORT_TTS_BACKEND_VOXCPM_URL
```

Remote overrides must be non-loopback. Local backend processes are launched and owned by the supervisor.

When a canonical launch command is known and portable for a backend family, it can be stored directly in the backend runtime definition and no command environment variable is needed.

### Higgs TTS Runtime Options

- **Full Higgs TTS 3** uses the reusable HTTP proxy driver plus `higgs-openai-server`.
- **Native Q4_K_M Higgs** uses `HiggsNativeDriver` around `audiocpp_engine.dll` and does not require a backend runtime.

The repository includes `native/audiocpp_engine.dll`; multi-GB model weights are excluded from Git.

## 5. Download the models you want

Use Model Hub to download/install ASR, translation, TTS, and optional diarization models appropriate for the target hardware and languages.

## 6. Create a voice profile

Open **Voice Profile Studio**, record or import a clean reference, and generate a preview. Add an exact transcript when the intended TTS manifest requires it.

---

# TTS Runtime Diagnostics

The Model Settings resource monitor includes a **TTS Runtime Profiles** row. Backend telemetry reports profile state plus managed backend model ID, backend runtime ID, backend runtime profile, PID, ephemeral endpoint, and health. An unexpected exit or unreachable managed backend marks the active runtime **broken**.

Logs are written under:

```text
data/logs/tts-worker-<profile>.log
data/logs/tts-backend-<backend-runtime>-<model-id>.log
```

---

# Model Licensing

Models from different vendors have different licenses. Review Model Hub metadata and [`docs/model-licenses.md`](docs/model-licenses.md) before distribution or commercial deployment.

---

# Privacy and Local-First Design

The reference translation path is local-first. Saved voice profiles remain local reusable assets. Local APIs, caption transport, and supervisor-managed TTS processes bind to localhost. Ephemeral worker/backend endpoints are runtime state, not persisted identity.

See [`docs/privacy-security.md`](docs/privacy-security.md).

---

# Development and Validation

Runtime Integrity covers routing, manifest/driver boundaries, backend runtime definitions, runtime-profile resolution, worker/backend process lifecycle, registry state, low-VRAM policies, XTTS helpers, and TTS supervisor recovery without downloading heavyweight TTS weights.

Useful local checks:

```bat
.venv\Scripts\python.exe -m compileall -q runtime agents tests benchmarks scripts
.venv\Scripts\python.exe -m pytest -q tests/integration tests/test_tts_backend_runtime_catalog.py tests/test_tts_plugin_architecture.py tests/test_tts_runtime_supervisor.py tests/test_tts_residency_contract.py tests/test_xtts_romanian.py
```

Hardware acceptance still requires the target GPU. Native Higgs, XTTS, and managed proxy backends should be measured on the RTX 2070 before treating VRAM/latency assumptions as validated.

---

# Documentation

- [Architecture](docs/architecture.md)
- [TTS Plugin, Backend Runtime & Runtime Profiles](docs/tts-plugin-architecture.md)
- [XTTS Romanian Low-VRAM](docs/xtts-romanian-low-vram.md)
- [Audio Routing](docs/audio-routing.md)
- [Model Bakeoff](docs/model-bakeoff.md)
- [Model Registry](docs/model-registry.md)
- [Model Discovery Agent](docs/model-discovery-agent.md)
- [Remote Workers](docs/remote-workers.md)
- [Google Meet Integration](docs/google-meet-integration.md)
- [Privacy & Security](docs/privacy-security.md)
- [Model Licenses](docs/model-licenses.md)
- [Troubleshooting](docs/troubleshooting.md)

---

# Project Direction

VoxPassport assumes speech AI will keep changing quickly. Model-specific behavior therefore stays behind stable capability boundaries.

For local TTS the rule is:

> **model manifest = model declaration; backend runtime = reusable server-family lifecycle; runtime profile = dependency family; supervisor = process topology/residency; driver = protocol/model implementation; `ManifestTtsAdapter` = application boundary.**

A new model on an already-supported backend family should require **one model manifest and nothing else**.
