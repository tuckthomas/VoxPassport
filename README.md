# Real-Time English ↔ Romanian Conference Translator

A local-first, real-time speech translation application for video/audio conferencing.

## Overview

This application enables full-duplex, real-time translation between English and Romanian during video conferences (Google Meet, Zoom, Teams, etc.). It captures speech, transcribes it, translates it, synthesizes translated speech, routes it into conference applications via a virtual microphone, and displays synchronized translated captions.

## Primary Use Case

- **Local user speaks English** → Remote participants hear Romanian (via virtual microphone)
- **Remote participant speaks Romanian** → Local user hears English (local audio only)

Both directions run simultaneously in `FULL_DUPLEX` mode.

## Architecture

```
Physical Microphone → VAD → ASR (EN) → MT (EN→RO) → TTS (RO) → Virtual Microphone → Conference
Conference Audio   → VAD → ASR (RO) → MT (RO→EN) → TTS (EN) → Local Headphones
```

All AI models are swappable through a runtime model registry. No model is hard-coded into business logic.

## Repository Structure

```
apps/
  desktop-companion/    # Tauri/Rust desktop UI, device selection, audio router
  browser-extension/    # Chrome MV3 extension for caption overlay

runtime/
  inference/
    adapters/           # ASR, MT, TTS, VAD adapters
    pipeline/           # Audio pipeline orchestration
    scheduler/          # GPU scheduling, backpressure, degraded modes
    model_registry/     # Model lifecycle, catalog, hot-swap
    metrics/            # Latency, resource tracking
    server/             # gRPC inference server

crates/
  audio-core/           # Platform-agnostic audio types
  audio-windows/        # WASAPI capture/playback
  audio-macos/          # CoreAudio integration
  audio-linux/          # PipeWire integration
  ipc-client/           # Desktop ↔ inference IPC
  protocol/             # Shared binary protocol types

packages/
  caption-protocol/     # Caption event schema
  shared-config/        # Configuration types

benchmarks/             # Model bakeoff harnesses
tests/                  # Unit, integration, e2e tests
configs/                # Example configuration files
docs/                   # Architecture and design docs
agents/                 # Model research agent
```

## Getting Started

### Prerequisites

- Windows 10/11 (primary), macOS, or Linux
- NVIDIA GPU with ≥8 GB VRAM (recommended: 12–16 GB)
- Python 3.12+
- Rust + Cargo (for desktop companion)
- A virtual audio cable driver (e.g., VB-Cable) for virtual microphone

### Quick Start

> **Not yet implemented.** See Milestone 0 in the plan for current status.

## Operating Modes

| Mode | Description |
|------|-------------|
| `FULL_DUPLEX` | Default. Both EN→RO and RO→EN pipelines run simultaneously. |
| `OUTBOUND_TRANSLATION` | Physical mic → EN ASR → RO MT → RO captions → RO TTS → virtual mic |
| `INBOUND_TRANSLATION` | Conference audio → RO ASR → EN MT → EN captions → EN TTS → local |
| `CAPTIONS_ONLY` | ASR + MT + captions only, no TTS |
| `TTS_NO_CLONE` | Stock/generated voice |
| `TTS_CLONED` | Enrolled speaker voice (when latency permits) |

## Privacy

- All inference runs on-device by default.
- No transcripts, audio, or speaker embeddings are persisted by default.
- Voice cloning requires explicit user enrollment — never automatic.
- See `docs/privacy-security.md` for details.

## Model Licenses

See `docs/model-licenses.md` for licensing information on all candidate models.

## Documentation

- [Architecture](docs/architecture.md)
- [Audio Routing](docs/audio-routing.md)
- [Model Bakeoff](docs/model-bakeoff.md)
- [Model Registry](docs/model-registry.md)
- [Model Discovery Agent](docs/model-discovery-agent.md)
- [Google Meet Integration](docs/google-meet-integration.md)
- [Privacy & Security](docs/privacy-security.md)
- [Troubleshooting](docs/troubleshooting.md)
