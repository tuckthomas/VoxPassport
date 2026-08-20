<div align="center">

# VoxPassport
### Local-First Multilingual Voice Translation for Live Conversations

<p>
  Real-time speech translation, captions, speaker-aware processing, and cross-lingual voice cloning for meetings, calls, and live conversation workflows.
</p>

<p>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python_3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12" /></a>
  <a href="https://pytorch.org/"><img src="https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white" alt="PyTorch" /></a>
  <a href="https://huggingface.co/"><img src="https://img.shields.io/badge/Hugging_Face-FFD21E?style=for-the-badge&logo=huggingface&logoColor=000" alt="Hugging Face" /></a>
  <a href="https://github.com/huggingface/transformers"><img src="https://img.shields.io/badge/Transformers-FFCC4D?style=for-the-badge&logo=huggingface&logoColor=000" alt="Transformers" /></a>
  <a href="https://developer.nvidia.com/cuda-zone"><img src="https://img.shields.io/badge/NVIDIA_CUDA-76B900?style=for-the-badge&logo=nvidia&logoColor=white" alt="NVIDIA CUDA" /></a>
  <a href="https://www.rust-lang.org/"><img src="https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white" alt="Rust" /></a>
  <a href="https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API"><img src="https://img.shields.io/badge/WebSockets-010101?style=for-the-badge&logo=socketdotio&logoColor=white" alt="WebSockets" /></a>
  <a href="https://docs.aiohttp.org/"><img src="https://img.shields.io/badge/aiohttp-2C5BB4?style=for-the-badge&logo=aiohttp&logoColor=white" alt="aiohttp" /></a>
  <a href="https://developer.chrome.com/docs/extensions/develop/migrate/what-is-mv3"><img src="https://img.shields.io/badge/Chrome_MV3-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white" alt="Chrome Manifest V3" /></a>
</p>

</div>

---

## Project Overview

**VoxPassport** is a local-first speech translation platform designed to make live multilingual conversation feel less like operating a translation tool and more like simply talking. It captures speech, detects voice activity, transcribes it, translates the resulting text, synthesizes the translation, and routes that audio to the appropriate listener or conference input while also publishing synchronized captions.

VoxPassport began as a way for me to have natural conversations with family members in Romania despite the language barrier. That personal use case shaped the project's emphasis on low-latency two-way conversation and preserving a speaker's voice across languages, but **VoxPassport is not an English/Romanian-only translator**. The runtime is built around configurable language pairs and swappable model adapters so additional languages can be supported whenever the selected ASR, translation, and TTS models support them. The model registry and Model Hub are deliberately separate from the pipeline so the application can evolve as newer multilingual models are released.

VoxPassport also treats **voice identity as a first-class part of translation**. A user can enroll a reusable, engine-agnostic voice profile and have translated speech synthesized in that voice using a compatible cloning model. The objective is not merely to translate *what* a person said, but—when the selected model supports it—to preserve *who sounds like they are speaking* across languages.

---

# Key Features

## Full-Duplex Multilingual Translation

VoxPassport can run both directions of a conversation simultaneously. Each audio direction has its own source and target language configuration, while the underlying multilingual ASR and translation models can be shared where appropriate.

```text
Local Microphone
    ↓
Voice Activity Detection
    ↓
ASR / Speech Recognition
    ↓
Text Translation
    ↓
TTS / Voice Cloning
    ↓
Virtual Microphone → Conference / Remote Listener

Remote Conference Audio
    ↓
Voice Activity Detection
    ↓
ASR / Speech Recognition
    ↓
Text Translation
    ↓
TTS / Voice Cloning
    ↓
Local Monitor / Headphones
```

The default development case is currently English ↔ Romanian, but the pipeline itself is language-pair driven rather than hard-coded to those two languages.

## Cross-Lingual Voice Cloning

Voice cloning is a core VoxPassport capability, not an optional afterthought. Voice Profile Studio records or imports a clean reference sample together with its exact transcript and stores it as an **engine-independent voice profile**. The active TTS backend consumes that same profile at synthesis time.

This architecture allows a voice profile to survive model changes. A user does **not** need to re-enroll a voice simply because OmniVoice is replaced by Higgs, MOSS, or another future cloning engine. Model-specific conditioning is generated at runtime and is not treated as the canonical voice identity.

The intended flow is:

```text
Reference recording + exact transcript
              ↓
      Universal voice profile
              ↓
   Active cloning-capable TTS
              ↓
Translated text in target language
              ↓
Speech in the enrolled speaker's voice
```

Cross-lingual quality and supported languages depend on the selected TTS model. VoxPassport therefore keeps voice profiles independent from the model that happens to be active.

## Model Hub and Hot-Swappable AI Stack

The application includes a model registry and Hugging Face-oriented Model Hub for discovering, downloading, installing, activating, replacing, and removing models without designing the application around a single AI vendor or model family.

Model capabilities are separated into slots such as:

- **VAD** — speech / non-speech detection
- **ASR** — automatic speech recognition
- **Translation / NMT** — text-to-text language translation
- **Direct Speech Translation** — experimental speech-to-translated-text paths
- **TTS** — speech synthesis and voice cloning
- **Diarization** — optional speaker-cluster tracking for inbound multi-speaker audio

Catalog entries distinguish between production/default models, benchmark candidates, and watchlist models whose upstream weights or runtime integrations are not yet ready for normal activation.

## Voice Profile Studio

Voice Profile Studio provides a controlled pre-conference workflow for creating and testing a voice profile before it is used live. The application normalizes the recording, stores the reference transcript, generates a cloned preview with the selected TTS model, and allows the profile to be saved as the active speaker identity.

VoxPassport intentionally avoids baking a specific TTS engine into the profile. The saved profile is the source recording and transcript; the currently active synthesis model decides how to condition on it.

## Live Studio

Live Studio is intended to exercise the **real local pipeline before a conference**. It uses the same ASR → translation → TTS path used by the runtime rather than a browser speech-recognition substitute. This makes it possible to validate language selection, transcription, translation, cloned speech, latency, and audio routing before joining a call.

## Debug and Verification Workflow

The verification tools provide a repeatable way to test the speech stack outside a meeting. They can transcribe supplied audio, translate it through the active local translation model, and compare round-trip output for debugging. This is intended to make model or routing failures visible before they become conference failures.

## Speaker Diarization

For inbound conference audio with multiple remote participants, VoxPassport can optionally run NVIDIA Streaming Sortformer as a **parallel diarization sidecar**. Diarization does not block ASR; speech recognition proceeds immediately while speaker-cluster metadata is attached when available.

Diarization labels such as `Speaker 1` and `Speaker 2` represent anonymous speaker clusters, not verified real-world identities. Named speaker identification would require a separate enrollment/matching layer.

## Live Captions and Conference Integration

The runtime publishes caption events over a local WebSocket service. The repository includes a desktop overlay and a Chrome Manifest V3 companion extension currently targeted at Google Meet. The broader runtime architecture is intended to remain conferencing-platform agnostic, with translated audio routed through local/virtual audio devices rather than requiring a cloud translation service.

---

# Current Model Architecture

VoxPassport is intentionally model-pluggable. The table below describes the current reference stack and notable alternatives in the repository; it is **not** a requirement that every model be installed at once.

| Capability | Current Reference / Default | Alternatives & Research Paths | Notes |
| :--- | :--- | :--- | :--- |
| **VAD** | Silero VAD v6.2.1 | Future VAD adapters | Lightweight, pinned runtime model |
| **ASR** | NVIDIA Parakeet TDT 0.6B v3 | Meta OmniASR CTC 300M / 1B; NVIDIA Canary-1B-v2 | Parakeet is multilingual and shared across both audio directions |
| **Translation** | Xiaomi MiLMMT-46 1B v1.0 | MiLMMT-46 4B v1.0; NVIDIA Riva Translate; Meta Omnilingual MT watchlist | 1B is the practical default; 4B is a heavier quality option |
| **TTS / Voice Cloning** | OmniVoice reference integration | Higgs TTS 3; MOSS-TTS v1.5; VoxCPM family; future cloning models | Language support, licensing, and hardware needs vary substantially by engine |
| **Direct Speech Translation** | Experimental | NVIDIA Canary-1B-v2 | Alternative to the ASR → NMT cascade; benchmark before making default |
| **Diarization** | Optional | NVIDIA Streaming Sortformer 4-Speaker v2.1 | Runs in parallel on inbound audio; not required for one-speaker streams |

The Model Hub is the source of truth for what is available, installed, active, downloadable, or watchlist-only on a particular system.

---

# Low-VRAM Runtime Policy

Real-time speech translation can involve several neural networks competing for one GPU. VoxPassport includes resource-management behavior specifically so an 8 GB-class GPU does not have to hold every model in VRAM simultaneously.

On lower-VRAM systems:

- both language directions share **one physical Parakeet model** rather than loading duplicate ASR weights;
- MiLMMT can run on CPU so GPU memory remains available for latency-sensitive speech models;
- optional Sortformer diarization can remain on CPU;
- heavyweight Parakeet ASR and native Higgs TTS inference are serialized on one GPU while audio capture and VAD continue buffering;
- OmniVoice loads lazily and creates conditioning only for the voice profile actually being used;
- only one OmniVoice clone prompt is retained in the runtime cache at a time.

Higher-memory systems can use more aggressive GPU residency and larger model variants. The correct hardware configuration therefore depends on the models the user chooses rather than on a single fixed VoxPassport requirement.

---

# Operating Modes

| Mode | Description |
| :--- | :--- |
| `FULL_DUPLEX` | Both translation directions run simultaneously. |
| `OUTBOUND_TRANSLATION` | Local microphone → ASR → translation → captions/TTS → virtual microphone. |
| `INBOUND_TRANSLATION` | Conference audio → ASR → translation → captions/TTS → local monitor. |
| `CAPTIONS_ONLY` | ASR + translation + captions without synthesized audio. |
| `TTS_NO_CLONE` | Use the active TTS engine without an enrolled cloned voice. |
| `TTS_CLONED` | Use the active voice profile with a cloning-capable TTS engine. |

Studio and verification workflows sit alongside these runtime modes so the same models can be tested before a real call.

---

# Architecture

VoxPassport is organized as a local inference runtime with thin UI and conference-integration layers around it.

```text
┌─────────────────────────────────────────────────────────────────┐
│                         VoxPassport Studio                      │
│ Voice Profiles • Live Studio • Debug • Model Hub • Configuration│
└──────────────────────────────┬──────────────────────────────────┘
                               │ localhost HTTP / WebSocket
┌──────────────────────────────▼──────────────────────────────────┐
│                    Unified Python Runtime                       │
│                                                                  │
│  Audio Capture → VAD → ASR → Translation → TTS → Audio Playback │
│                           │                                      │
│                           ├── Caption Events                      │
│                           ├── Model Registry / Hot-Swap           │
│                           └── Optional Parallel Diarization       │
└───────────────┬───────────────────────────────┬──────────────────┘
                │                               │
        Virtual / Local Audio             Browser / Overlay
                │                               │
         Meeting Platform                Live Captions
```

### Core Runtime Technologies

- **Python 3.12** — inference daemon, orchestration, model management, APIs
- **PyTorch** — local neural inference and CUDA execution
- **Hugging Face Transformers / Hub** — model execution and model acquisition
- **aiohttp** — local Studio/API server
- **WebSockets** — live caption/event transport
- **NumPy / SciPy / SoundFile / SoundDevice** — audio DSP, resampling, capture, and playback
- **Rust workspace** — native audio/protocol components, including Windows audio work
- **HTML / CSS / JavaScript** — Studio, model manager, overlays, and browser companion UI
- **Chrome Manifest V3** — current Google Meet browser-extension integration
- **FFmpeg** — normalization of imported voice-reference audio

---

# Repository Structure

```text
VoxPassport/
├── apps/
│   ├── browser-extension/              # Chrome MV3 Google Meet caption companion
│   └── desktop-companion/
│       ├── model-manager/              # VoxPassport Studio + Model Hub UI
│       └── overlay/                    # Local caption overlay
├── runtime/inference/
│   ├── adapters/                       # VAD, ASR, MT, TTS, diarization adapters
│   ├── model_registry/                 # Catalog, install state, active models, hot-swap
│   ├── pipeline/                       # Full-duplex audio/translation orchestration
│   ├── scheduler/                      # Runtime/degraded-mode scheduling
│   ├── metrics/                        # Latency and runtime metrics
│   └── server/                         # Unified local API + inference daemon
├── agents/                             # Model discovery/research automation
├── crates/
│   ├── audio-core/                     # Native audio abstractions
│   ├── audio-windows/                  # Windows audio implementation
│   └── protocol/                       # Shared native protocol types
├── benchmarks/                         # Model bakeoff and performance tooling
├── tests/                              # Unit/integration/runtime integrity tests
├── configs/                            # Runtime configuration examples
├── docs/                               # Architecture, routing, privacy, model docs
├── install.bat                         # Windows Python environment setup
└── run.bat                             # Windows runtime launcher
```

---

# Installation

## System Requirements

There is intentionally **no single VRAM number that defines VoxPassport**. Hardware requirements are determined by the models and quality modes a user installs and activates.

| Resource | Practical Guidance |
| :--- | :--- |
| **Operating System** | Windows 10/11 is the current primary development target. |
| **Python** | Python 3.12 recommended for the current runtime. |
| **GPU** | NVIDIA CUDA GPU strongly recommended for real-time local speech inference. CPU-only execution may be possible for some models but will generally be slower. |
| **VRAM** | ~8 GB can run the lightweight/reference stack with the low-VRAM residency policy; larger TTS/MT models may require substantially more or separate workers. |
| **RAM** | Depends on CPU-offloaded and selected models. More RAM is useful on lower-VRAM systems because translation/diarization may intentionally run on CPU. |
| **Storage** | Model-dependent. Individual checkpoints range from small VAD assets to multi-gigabyte ASR, MT, and TTS models. |
| **Audio Routing** | A virtual audio input/device is required when translated speech must be injected into a conferencing application. |
| **FFmpeg** | Required for normalizing imported voice-profile recordings. |

The Model Hub catalog exposes model-specific download size, runtime, licensing, and expected hardware information where known. **Do not assume that every catalog model is intended to be resident simultaneously.**

## 1. Clone the Repository

```bash
git clone https://github.com/tuckthomas/VoxPassport.git
cd VoxPassport
```

## 2. Install the Python Runtime

On Windows:

```bat
install.bat
```

The installer creates `.venv` if necessary and installs `runtime/inference/requirements.txt`.

For a manual setup:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r runtime/inference/requirements.txt
```

## 3. Start VoxPassport

```bat
run.bat
```

Or start the daemon directly:

```bash
python runtime/inference/server/main.py
```

The current local services are:

| Service | Address | Purpose |
| :--- | :--- | :--- |
| **Studio / Model Manager** | `http://127.0.0.1:8766/manager/index.html` | Voice profiles, model management, Live Studio, debugging |
| **Local API** | `http://127.0.0.1:8766` | Runtime/model/voice endpoints |
| **Caption WebSocket** | `ws://127.0.0.1:8765/ws/captions` | Live caption and translation events |

### Higgs TTS Runtime Options

VoxPassport supports two Higgs TTS paths:

- **Full Higgs TTS 3** uses the existing SGLang/Omni worker and the standard `higgs-tts-3` model. This remains the broadest path for longer reference conditioning and higher-memory GPUs.
- **Native Q4_K_M Higgs** uses a locally compiled or compatible prebuilt `audiocpp_engine.dll` with the `higgs-tts-3-q4_k_m` GGUF package. It supports native reference-audio voice cloning through `audiocpp_generate_voice_clone_stream`, including the multilingual targets exposed by the Studio and live pipeline. On 8 GB GPUs, VoxPassport creates a reusable five-second conditioning reference, persists the DLL's processed-speaker `.hspkcache`, generates deterministic short clauses, and streams decoded audio as it becomes available. The saved reference recording is never shortened or overwritten.

The native DLL is not limited to the RTX 2070. That GPU requires a build containing `sm_75`, while newer NVIDIA GPUs can use a compatible prebuilt DLL containing their architecture (for example `sm_86`, `sm_89`, or newer). If no compatible native DLL is present, VoxPassport continues to expose the full Higgs/SGLang path instead of treating the native package as installed.

For local native deployment, place the engine at `native/audiocpp_engine.dll` or set `VOXPASSPORT_HIGGS_NATIVE_DLL` to its absolute path. Place the quantized model at `models/higgs-tts-3-q4_k_m/`; the Model Settings → Active Engines page registers it automatically when both the GGUF and DLL are present. The native loader also honors `CUDA_PATH` for CUDA runtime dependencies.

On an 8 GB card, Parakeet ASR remains resident because live transcription is still required, while MiLMMT translation runs on CPU and VAD remains lightweight. VoxPassport serializes the heavy ASR and TTS CUDA execution instead of unloading and reloading Parakeet for every phrase; microphone and conference capture continue during synthesis, and queued audio is transcribed when the GPU becomes available. Unused TTS engines and optional GPU sidecars should not be kept resident alongside native Higgs.

## 4. Download the Models You Want

Large model weights are not intended to be bundled blindly with the repository. Use **Model Hub** inside VoxPassport to download the ASR, translation, TTS, and optional diarization models appropriate for your hardware and target languages.

Some runtime-managed models, such as Silero VAD, are acquired by their adapter rather than through the normal Hugging Face download button. Watchlist entries are intentionally not presented as downloadable when no official upstream checkpoint has been wired.

## 5. Create a Voice Profile

Open **Voice Profile Studio**, record or import a clean reference sample, provide the exact transcript, and generate a preview. Once saved, the profile can be used by any compatible active cloning engine without being permanently bound to the model used during enrollment.

---

# Model Licensing

VoxPassport can orchestrate models from multiple vendors, and **their licenses are not interchangeable**. Some models permit commercial use, some impose attribution or model-specific terms, and some voice-cloning checkpoints are research/non-commercial unless separately licensed.

Before deploying a particular configuration, review both the Model Hub metadata and [`docs/model-licenses.md`](docs/model-licenses.md). Installing a model in VoxPassport does not change the license of that model.

---

# Privacy and Local-First Design

The core translation path is designed for local inference. Conference audio and translated text do not need to be sent to a cloud translation provider for the reference pipeline to function.

Saved voice profiles are deliberately persisted **locally** because they are reusable user assets. A profile contains the normalized reference recording, its transcript, and profile metadata. Model-specific voice-conditioning prompts are runtime artifacts rather than the canonical stored identity.

The local HTTP and caption services bind to `127.0.0.1` in the current runtime. See [`docs/privacy-security.md`](docs/privacy-security.md) for the broader privacy/security design.

---

# Development and Validation

VoxPassport is under active development. The project includes a Runtime Integrity GitHub Actions workflow plus integration tests covering model routing, TTS backend separation, full-duplex streaming, registry state, VAD behavior, diarization architecture, and low-VRAM policies.

Useful local checks include:

```bash
python -m compileall -q runtime agents tests
python -m pytest -q tests/integration
```

For model work, benchmark changes against the existing reference stack rather than assuming that a newer or larger checkpoint is automatically better. Real-time translation quality depends on several dimensions at once: transcription accuracy, language coverage, first-token/first-audio latency, stream stability, translation quality, voice fidelity, VRAM pressure, and end-to-end conversational delay.

---

# Documentation

- [Architecture](docs/architecture.md)
- [Audio Routing](docs/audio-routing.md)
- [Model Bakeoff](docs/model-bakeoff.md)
- [Model Registry](docs/model-registry.md)
- [Model Discovery Agent](docs/model-discovery-agent.md)
- [Google Meet Integration](docs/google-meet-integration.md)
- [Privacy & Security](docs/privacy-security.md)
- [Model Licenses](docs/model-licenses.md)
- [Troubleshooting](docs/troubleshooting.md)

---

# Project Direction

VoxPassport is being built around one assumption: **speech AI will keep changing quickly**. The application therefore should not depend on today's best ASR, translation, diarization, or voice-cloning model remaining the best choice six months from now.

The long-term goal is a conference and conversation layer where users can select the best models for their languages and hardware, test them before a call, preserve speaker identity where appropriate, and replace individual components without rewriting the rest of the application.
