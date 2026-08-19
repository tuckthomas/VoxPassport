# Architecture — Real-Time English ↔ Romanian Translator

## System Overview

The application is divided into three main layers:

1. **Desktop Companion** (Rust/Tauri) — UI, device selection, audio routing, overlay
2. **Local Inference Runtime** (Python) — VAD, ASR, MT, TTS, model registry, scheduling
3. **Browser Companion** (Chrome Extension) — Caption overlay, controls (optional)

## Audio Pipeline

### Outbound (English → Romanian)

```
Physical Microphone
        │
        ▼
Audio Capture (WASAPI/CoreAudio/PipeWire)
        │
        ▼
AEC / Noise Suppression / Gain Control
        │
        ▼
VAD + Endpointing (Silero VAD)
        │
        ▼
Streaming ASR (English) — Nemotron 3.5 Streaming 0.6B
        │
        ├──────────────► Source Caption Event
        │
        ▼
Stable-Prefix / PhraseCommitter
        │
        ▼
Machine Translation (EN → RO) — MiLMMT-46
        │
        ├──────────────► Translated Caption Event
        │
        ▼
TTS (Romanian) — OmniVoice
        │
        ▼
Streaming PCM Resampler / Jitter Buffer
        │
        ▼
BUS_VIRTUAL_MIC → Conference Application
```

### Inbound (Romanian → English)

```
Conference Output / OS Loopback (BUS_REMOTE_CONFERENCE)
        │
        ▼
Remote Audio Capture
        │
        ▼
VAD + Endpointing
        │
        ▼
Streaming ASR (Romanian) — Nemotron 3.5 Streaming 0.6B
        │
        ├──────────────► Source Caption Event
        │
        ▼
Stable-Prefix / PhraseCommitter
        │
        ▼
Machine Translation (RO → EN) — MiLMMT-46
        │
        ├──────────────► Translated Caption Event
        │
        ▼
Optional English TTS — OmniVoice
        │
        ▼
BUS_LOCAL_MONITOR → Local Headphones/Speakers ONLY
```

## Audio Bus Isolation

| Bus | Description |
|-----|-------------|
| `BUS_PHYSICAL_MIC` | Raw capture from local physical microphone |
| `BUS_REMOTE_CONFERENCE` | Conference output / OS loopback |
| `BUS_OUTBOUND_TRANSLATED_TTS` | Romanian TTS output (outbound direction) |
| `BUS_INBOUND_TRANSLATED_TTS` | English TTS output (inbound direction) |
| `BUS_VIRTUAL_MIC` | Output device consumed by conference apps |
| `BUS_LOCAL_MONITOR` | Local headphone/speaker monitoring |

**Rules:**
- `BUS_OUTBOUND_TRANSLATED_TTS` → `BUS_VIRTUAL_MIC` ✓
- `BUS_INBOUND_TRANSLATED_TTS` → `BUS_LOCAL_MONITOR` ✓ (never `BUS_VIRTUAL_MIC`)
- No bus feeds back into its own capture source.

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Desktop Companion                        │
│  UI + Device Selection + Audio Router + Overlay Controller  │
└───────────────┬───────────────────────┬─────────────────────┘
                │                       │
          Audio Frames             Control / Events
                │                       │
                ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│                 Local Inference Runtime                     │
│                                                             │
│  VAD → ASR Adapter → PhraseCommitter → MT Adapter → TTS     │
│                                                             │
│  Model Registry | Scheduler | Metrics | Health | Config     │
└─────────────────────────────┬───────────────────────────────┘
                              │
                        Caption Events
                              │
             ┌────────────────┴─────────────────┐
             ▼                                  ▼
  Desktop Caption Overlay             Browser/Meet Companion
```

## IPC Protocol

- Desktop ↔ Inference: gRPC bidirectional streaming (audio frames, caption events, control)
- Inference ↔ Browser Extension: Local WebSocket (127.0.0.1 only, session token auth)
- PCM audio is never serialized as JSON — binary framing only.

## Model Hot-Swap

All models are managed through the `ModelRegistry`. The application requests models by capability:

```python
get_active_model(capability="ASR", language_pair="en-ro")
get_active_model(capability="TRANSLATION", language_pair="en-ro")
get_active_model(capability="TTS", language="ro")
```

Hot-swap states: `REQUESTED → PRELOADING → READY → DRAINING_OLD_MODEL → ACTIVE`

Rollback is automatic on failure. See `docs/model-registry.md` for full lifecycle.

## Milestone Roadmap

| Milestone | Description | Status |
|-----------|-------------|--------|
| 0 | Offline model bakeoff | 🔲 Not started |
| 1 | Live mic → captions | 🔲 Not started |
| 2 | TTS playback | 🔲 Not started |
| 3 | Virtual microphone | 🔲 Not started |
| 4 | Inbound RO → EN | 🔲 Not started |
| 5 | Full duplex | 🔲 Not started |
| 6 | Voice cloning | 🔲 Not started |
| 7 | Caption overlay | 🔲 Not started |
| 8 | Meet-native integration | 🔲 Optional |

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Desktop app | Rust + Tauri 2 |
| Audio capture/routing | Rust (WASAPI/CoreAudio/PipeWire) |
| Inference runtime | Python 3.12+ |
| ML framework | PyTorch + HuggingFace Transformers |
| Specialized runtimes | NVIDIA NeMo (where required) |
| IPC | gRPC streaming |
| Caption events | WebSocket (local only) |
| Browser extension | Chrome MV3 |
