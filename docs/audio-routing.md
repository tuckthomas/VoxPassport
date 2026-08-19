# Audio Routing — LiveTranslator

## Bus Definitions

### BUS_PHYSICAL_MIC
- **Source:** Physical microphone selected by the user
- **Consumer:** Outbound pipeline (VAD → ASR → MT → TTS)
- **Platform:** WASAPI exclusive/shared mode (Windows), CoreAudio (macOS), PipeWire (Linux)
- **Never feeds:** Any output bus directly

### BUS_REMOTE_CONFERENCE
- **Source:** Conference application output / OS loopback
- **Consumer:** Inbound pipeline (VAD → ASR → MT → TTS)
- **Platform:** WASAPI loopback (Windows), ScreenCaptureKit (macOS), PipeWire monitor (Linux)
- **Never feeds:** Virtual mic

### BUS_OUTBOUND_TRANSLATED_TTS
- **Source:** Romanian TTS output from the outbound pipeline
- **Consumer:** BUS_VIRTUAL_MIC
- **Never feeds:** BUS_LOCAL_MONITOR or any inbound capture source

### BUS_INBOUND_TRANSLATED_TTS
- **Source:** English TTS output from the inbound pipeline
- **Consumer:** BUS_LOCAL_MONITOR (user's headphones/speakers)
- **Never feeds:** BUS_VIRTUAL_MIC

### BUS_VIRTUAL_MIC
- **Source:** BUS_OUTBOUND_TRANSLATED_TTS
- **Consumer:** Conference applications (Google Meet, Zoom, Teams, etc.)
- **Implementation:** Virtual audio cable driver (VB-Cable, VBVMIX, etc.)

### BUS_LOCAL_MONITOR
- **Source:** BUS_INBOUND_TRANSLATED_TTS
- **Consumer:** Local headphones or speakers
- **Must not be captured** as part of conference loopback

## Anti-Feedback Rules

1. The application assigns each synthesized utterance an internal `utterance_id`.
2. Known synthesized output device IDs are excluded from loopback capture scope where possible.
3. If an utterance matches a recently-spoken synthesized text hash, it is suppressed as a recursive loop.
4. A watchdog monitors for repeated identical transcript sequences and raises `RECURSION_SUSPECTED` alert.

## Windows WASAPI Routing

```
Physical Mic (Capture Device)
    └─► WasapiCapture(exclusive/shared) → BUS_PHYSICAL_MIC

Conference App Output (Render Device)
    └─► WasapiLoopbackCapture → BUS_REMOTE_CONFERENCE

Romanian TTS PCM
    └─► VirtualCableWriter → BUS_VIRTUAL_MIC → Conference App Mic Input

English TTS PCM
    └─► WasapiRender(headphones) → BUS_LOCAL_MONITOR
```

## Sample Rate Management

All internal processing uses explicit sample rates. Resampling happens in one dedicated layer:

| Stage | Required Sample Rate |
|-------|---------------------|
| Nemotron 3.5 ASR | 16 kHz, mono |
| MiLMMT MT | N/A (text only) |
| OmniVoice TTS output | 24 kHz or 48 kHz (model-native) |
| Virtual mic expected | 48 kHz, stereo (Windows default) |
| Local monitor | Device native |

**Rule:** Never resample more than once. Convert from capture-native → model-required in one step, and from TTS-native → output-required in one step.

## AEC / Noise Suppression

- WebRTC Audio Processing Module (APM) or equivalent applied on `BUS_PHYSICAL_MIC`
- AEC reference signal: conference output from `BUS_REMOTE_CONFERENCE`
- This prevents the remote Romanian TTS playback from corrupting the local English mic capture
