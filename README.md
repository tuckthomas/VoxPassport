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
  <a href="https://www.rust-lang.org/"><img src="https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white" alt="Rust" /></a>
  <a href="https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API"><img src="https://img.shields.io/badge/WebSockets-010101?style=for-the-badge&logo=socketdotio&logoColor=white" alt="WebSockets" /></a>
  <a href="https://docs.aiohttp.org/"><img src="https://img.shields.io/badge/aiohttp-2C5BB4?style=for-the-badge&logo=aiohttp&logoColor=white" alt="aiohttp" /></a>
</p>

</div>

---

## Project Overview

**VoxPassport** is a modular local-first audio and language platform with two complementary roles: a live multilingual translation-and-captioning workspace and a voice-cloning/TTS studio. It can run an end-to-end conversation workflow—capturing speech, detecting voice activity, transcribing it, translating the resulting text, synthesizing translated speech, routing audio to the correct listener or conference input, and publishing synchronized captions—but no single workflow requires every capability or model to be enabled.

The same application can also be used for independent tasks: speech-to-text only, text translation only, standalone voice cloning/TTS, or captions without synthesized audio. The model registry and Model Hub are deliberately separate from the pipeline so the active AI stack can evolve without rewriting the application around one vendor or model family.

VoxPassport began as a way for me to have natural conversations with family members in Romania despite the language barrier. That use case shaped the project's emphasis on low-latency two-way conversation and preserving a speaker's voice across languages, but **VoxPassport is not an English/Romanian-only translator**. The runtime is language-pair driven; actual language coverage comes from the selected ASR, translation, and TTS models.

VoxPassport treats **voice identity as a first-class platform capability**. A user can enroll a reusable, engine-agnostic voice profile and use it for standalone text-to-speech or translated speech synthesized in that voice using a compatible cloning model.

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

VoxPassport can run both directions of a conversation simultaneously. Each direction has separate source/target state and audio routing, while physical model instances can be shared where appropriate.

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

Bidirectionality does not require loading two copies of every model. The current low-VRAM design can share one Parakeet model, one MiLMMT model, and one active TTS model across both logical directions.

## Cross-Lingual Voice Cloning

Voice Profile Studio records or imports a clean reference sample and stores it as an **engine-independent voice profile**. A reference transcript can also be stored, but it is no longer globally mandatory: the selected TTS manifest declares whether that engine actually requires one.

This allows a voice profile to survive model changes. Replacing OmniVoice with Higgs, MOSS, XTTS, or another compatible cloning engine does not require a model-bound duplicate profile.

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

Model-specific conditioning may be derived at runtime, but it is not the canonical stored voice identity.

## Manifest-Driven Local TTS

All local TTS engines use one application architecture:

```text
Main VoxPassport runtime
        │
        ▼
ManifestTtsAdapter
        │ voxpassport.tts.v1
        ▼
Generic TTS worker host
        │
        ▼
TtsDriver
        │
        └── model library / native DLL / local backend
```

There are no model-specific local TTS application adapters and no special native-Higgs or OmniVoice application path. Current local TTS manifests include OmniVoice, full Higgs TTS 3, native Higgs Q4_K_M, MOSS-TTS v1.5, VoxCPM2, and XTTS-v2 Romanian v2.

Model identity, aliases, capabilities, driver entrypoints, and registry metadata live in `runtime/tts_manifests/*.json`. Model-specific inference behavior lives behind worker-side `TtsDriver` implementations. The main daemon and orchestrator should not branch on TTS model names.

See [`docs/tts-plugin-architecture.md`](docs/tts-plugin-architecture.md).

## Dependency-Isolated TTS Workers

A stable protocol boundary lets incompatible Python dependency sets run in separate processes without creating separate application architectures.

The current launcher uses:

```text
.venv       → generic TTS host on 127.0.0.1:8098
.venv-xtts  → same generic TTS host on 127.0.0.1:8099, when installed
main daemon → runtime/inference/server/main.py
```

XTTS is isolated because Coqui's dependency constraints should not pin or destabilize the main Parakeet/Transformers environment. The primary runtime currently follows Hugging Face Transformers from Git source, whereas the XTTS environment constrains Transformers to the Coqui-compatible range.

**The separate virtual environment is intentional and desirable. The fixed port topology is not the long-term ideal.** The preferred evolution is a runtime-profile supervisor that maps a manifest's runtime requirements to an interpreter/environment, starts the generic worker on demand, assigns/discovers its endpoint, enforces GPU residency, and shuts down idle workers. Runtime profiles should be grouped by dependency compatibility rather than creating one environment per model.

## Model Hub and Hot-Swappable AI Stack

The application includes a model registry and Hugging Face-oriented Model Hub for discovering, downloading, installing, activating, replacing, and removing models.

Capability slots include:

- **VAD** — speech / non-speech detection
- **ASR** — automatic speech recognition
- **Translation / NMT** — text-to-text translation
- **Direct Speech Translation** — experimental speech-to-translated-text paths
- **TTS** — speech synthesis and voice cloning
- **Diarization** — optional speaker-cluster tracking for inbound multi-speaker audio

Local TTS metadata is sourced from TTS manifests and bridged into the registry; it is not duplicated in the general built-in model catalog.

## Voice Profile Studio

Voice Profile Studio provides a controlled pre-conference workflow for recording/importing a reference, previewing the selected TTS engine, and saving the profile as a reusable speaker identity.

The currently active TTS model decides how to condition on the profile. Transcript validation is capability-driven, so models that do not need a transcript can use a recording-only profile while models that require one still fail clearly when it is missing.

## Live Studio

Live Studio is intended to exercise the real local pipeline before a conference. It uses the same ASR → translation → TTS path as the runtime so language selection, transcription, translation, cloned speech, latency, and routing can be validated before joining a call.

## Speaker Diarization

For inbound conference audio with multiple remote participants, VoxPassport can optionally run NVIDIA Streaming Sortformer as a parallel diarization sidecar. Diarization does not block ASR; speaker-cluster metadata is attached when available.

Diarization labels represent anonymous clusters, not verified identities.

## Live Captions and Conference Integration

The runtime publishes caption events over a localhost WebSocket service. The repository includes a desktop overlay and a Chrome Manifest V3 browser companion currently targeted at Google Meet. The broader runtime remains conferencing-platform agnostic.

---

# Current Model Architecture

| Capability | Current Reference / Default | Alternatives & Research Paths | Notes |
| :--- | :--- | :--- | :--- |
| **VAD** | Silero VAD v6.2.1 | Future VAD adapters | Lightweight, pinned runtime model |
| **ASR** | NVIDIA Parakeet TDT 0.6B v3 | Meta OmniASR CTC 300M / 1B; NVIDIA Canary-1B-v2 | One physical Parakeet model can serve both directions |
| **Translation** | Xiaomi MiLMMT-46 1B v1.0 | MiLMMT-46 4B v1.0; NVIDIA Riva Translate; Meta Omnilingual MT watchlist | 1B is the practical low-VRAM choice |
| **TTS / Voice Cloning** | OmniVoice reference integration | Native/full Higgs, MOSS, VoxCPM, XTTS Romanian | All local options use manifests + `voxpassport.tts.v1` |
| **Direct Speech Translation** | Experimental | NVIDIA Canary-1B-v2 | Benchmark before replacing the ASR → NMT cascade |
| **Diarization** | Optional | NVIDIA Streaming Sortformer 4-Speaker v2.1 | Parallel inbound sidecar |

The Model Hub is the source of truth for what is available, installed, active, downloadable, or watchlist-only on a particular system.

---

# Low-VRAM Runtime Policy

Real-time speech translation can involve several neural networks competing for one GPU. On lower-VRAM systems VoxPassport is designed so every model does not need to be resident or active on CUDA simultaneously.

Current policies include:

- both language directions can share one physical Parakeet model;
- MiLMMT can run on CPU so GPU memory remains available for latency-sensitive speech inference;
- optional Sortformer diarization can remain on CPU;
- heavyweight ASR and local TTS requests are coordinated instead of intentionally launching competing GPU work at the same time;
- audio capture and VAD continue while heavyweight GPU inference is busy;
- OmniVoice loads weights lazily and bounds its speaker-conditioning cache;
- native Higgs runtime VRAM is treated as more than the GGUF weight-file size because caches, activations, CUDA workspaces, and scratch buffers also consume memory;
- switching TTS engines unloads the prior worker-side model, including cross-environment XTTS switches.

Higher-memory systems can use more aggressive residency and larger model variants.

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

---

# Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│                           VoxPassport                            │
│ Voice Profiles • Live Studio • Debug • Model Hub • Configuration│
└───────────────────────────────┬──────────────────────────────────┘
                                │ localhost HTTP / WebSocket
┌───────────────────────────────▼──────────────────────────────────┐
│                      Main Python Runtime                         │
│                                                                  │
│ Audio Capture → VAD → ASR → Translation → ManifestTtsAdapter    │
│      │                         │                                  │
│      │                         ├── Model Registry / Hot-Swap      │
│      │                         ├── Caption Events                  │
│      │                         └── Optional Diarization            │
│      │                                                            │
│      └──────────────────────────────► Audio Playback / Routing    │
└───────────────────────────────┬──────────────────────────────────┘
                                │ voxpassport.tts.v1
                  ┌─────────────┴─────────────┐
                  ▼                           ▼
       Generic TTS host :8098      Generic TTS host :8099
       primary environment         isolated XTTS environment
                  │                           │
                  ▼                           ▼
             TtsDriver                    TtsDriver
```

The two TTS hosts are currently a process/dependency topology, not separate TTS architectures. The target evolution is a runtime-profile supervisor that removes fixed model-to-port coupling.

### Core Runtime Technologies

- **Python 3.12** — inference daemon, orchestration, model management, APIs, TTS worker hosts
- **PyTorch** — local neural inference and CUDA execution
- **Hugging Face Transformers / Hub** — model execution and model acquisition
- **aiohttp** — local APIs and TTS worker protocol
- **WebSockets** — caption/event transport
- **NumPy / SciPy / SoundFile / SoundDevice** — audio DSP, resampling, capture, and playback
- **Rust workspace** — native audio/protocol components
- **HTML / CSS / JavaScript** — Studio, model manager, overlays, and browser companion UI
- **FFmpeg** — normalization of imported voice-reference audio

---

# Repository Structure

```text
VoxPassport/
├── apps/
│   ├── browser-extension/
│   └── desktop-companion/
├── runtime/
│   ├── inference/
│   │   ├── adapters/                   # VAD/ASR/MT plus generic local TTS adapter
│   │   ├── model_registry/             # install state, active models, hot-swap
│   │   ├── pipeline/                   # full-duplex orchestration
│   │   ├── scheduler/
│   │   ├── metrics/
│   │   ├── tts_plugins/                # TTS manifest loader + registry bridge
│   │   └── server/                     # unified local API / daemon
│   ├── tts_manifests/                  # sole local TTS model declarations
│   └── workers/tts_host/               # generic voxpassport.tts.v1 host + drivers
├── .agents/plans/
├── crates/
├── benchmarks/
├── tests/
├── configs/
├── docs/
├── install.bat
├── install_xtts_worker.bat
└── run.bat
```

---

# Installation

## System Requirements

There is intentionally no single VRAM number that defines VoxPassport. Requirements depend on the models and quality modes installed and activated.

| Resource | Practical Guidance |
| :--- | :--- |
| **Operating System** | Windows 10/11 is the current primary development target. |
| **Python** | Python 3.12 for the current runtime. |
| **GPU** | NVIDIA CUDA GPU strongly recommended for real-time local speech inference. |
| **VRAM** | ~8 GB can run the lightweight/reference stack with low-VRAM policy; larger models may require more memory or more aggressive swapping. |
| **RAM** | Additional RAM is useful when translation/diarization are intentionally CPU-resident. |
| **Storage** | Model-dependent; checkpoints range from small VAD assets to multi-GB speech models. |
| **Audio Routing** | A virtual audio input/device is required to inject translated speech into a conferencing application. |
| **FFmpeg** | Required for normalization of imported voice-profile recordings. |

## 1. Clone

```bash
git clone https://github.com/tuckthomas/VoxPassport.git
cd VoxPassport
```

## 2. Install the primary runtime

```bat
install.bat
```

The installer creates the project-local `.venv` and installs the tested Windows CUDA PyTorch/TorchAudio stack plus `runtime/inference/requirements.txt`.

## 3. Optional: install the XTTS dependency profile

```bat
install_xtts_worker.bat
```

This creates `.venv-xtts` rather than injecting Coqui/XTTS dependencies into the main environment. Install it only if XTTS is needed.

## 4. Start VoxPassport

```bat
run.bat
```

Or start only the main daemon:

```bat
.venv\Scripts\python.exe runtime\inference\server\main.py
```

Current local services include:

| Service | Address | Purpose |
| :--- | :--- | :--- |
| **Studio / Model Manager** | `http://127.0.0.1:8766/manager/index.html` | Voice profiles, model management, Live Studio, debugging |
| **Local API** | `http://127.0.0.1:8766` | Runtime/model/voice endpoints |
| **Caption WebSocket** | `ws://127.0.0.1:8765/ws/captions` | Live caption and translation events |
| **Primary generic TTS host** | `http://127.0.0.1:8098` | Local TTS drivers using the primary environment |
| **XTTS generic TTS host** | `http://127.0.0.1:8099` | Same protocol under `.venv-xtts`, when installed |

### Higgs TTS Runtime Options

VoxPassport exposes both Higgs paths through manifests and worker-side drivers:

- **Full Higgs TTS 3** uses the reusable HTTP proxy driver to reach the configured Higgs/SGLang-compatible backend.
- **Native Q4_K_M Higgs** uses `HiggsNativeDriver` around `audiocpp_engine.dll` and the `higgs-tts-3-q4_k_m` GGUF package.

The repository currently includes `native/audiocpp_engine.dll`; the multi-GB model weights are intentionally excluded from Git. The native Higgs manifest is known to the registry, but the driver can only load successfully when the required DLL, CUDA runtime dependencies, and model package are present.

On an 8 GB card, runtime policy should keep the GPU focused on the latency-sensitive model currently doing work rather than keeping unrelated heavyweight TTS engines resident.

## 5. Download the models you want

Use Model Hub to download/install the ASR, translation, TTS, and optional diarization models appropriate for the hardware and target languages. Some runtime-managed models such as Silero VAD are acquired outside the normal Hugging Face download button.

## 6. Create a voice profile

Open **Voice Profile Studio**, record or import a clean reference, and generate a preview. Add an exact transcript when the intended cloning model requires it. The profile itself remains model-independent.

---

# Model Licensing

VoxPassport can orchestrate models from multiple vendors, and their licenses are not interchangeable. Review both Model Hub metadata and [`docs/model-licenses.md`](docs/model-licenses.md) before distribution or commercial deployment.

---

# Privacy and Local-First Design

The reference translation path is designed for local inference. Saved voice profiles are local reusable assets. A canonical profile consists of the reference recording, optional transcript, and profile metadata; model-specific conditioning is a derived runtime/profile artifact rather than the canonical identity.

Local APIs, caption transport, and local TTS workers bind to localhost in the current implementation. See [`docs/privacy-security.md`](docs/privacy-security.md).

---

# Development and Validation

VoxPassport is under active development. Runtime Integrity covers model routing, TTS architectural boundaries, registry state, VAD behavior, diarization architecture, XTTS pure helpers, and low-VRAM policies without downloading heavyweight TTS weights.

Useful local checks include:

```bat
.venv\Scripts\python.exe -m compileall -q runtime agents tests benchmarks scripts
.venv\Scripts\python.exe -m pytest -q tests/integration tests/test_tts_plugin_architecture.py tests/test_xtts_romanian.py
```

Hardware acceptance tests still need the actual target GPU. In particular, native Higgs and the XTTS 50-turn soak should be benchmarked on the RTX 2070 before treating latency/VRAM assumptions as validated.

---

# Documentation

- [Architecture](docs/architecture.md)
- [TTS Plugin Architecture](docs/tts-plugin-architecture.md)
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

VoxPassport is built around the assumption that speech AI will keep changing quickly. The application therefore should not depend on today's best ASR, translation, diarization, or voice-cloning model remaining the best choice.

The architectural rule is to isolate model-specific behavior behind stable capability and worker boundaries. For local TTS, that means manifests + `ManifestTtsAdapter` + `voxpassport.tts.v1` + worker-side drivers. For dependency-conflicting model families, the next scaling step is supervisor-managed runtime profiles rather than expanding hard-coded per-model hosts.
