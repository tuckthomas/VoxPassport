# Audio Routing — VoxPassport

## Routing model

VoxPassport keeps capture, inference, translated output, conference injection, and local monitoring as distinct buses. The same logical bus contract is implemented on Windows, macOS, and Linux through platform-native audio helpers.

## Bus definitions

### `BUS_PHYSICAL_MIC`

- **Source:** physical microphone selected by stable platform endpoint ID.
- **Consumer:** outbound translation pipeline.
- **Windows:** WASAPI capture.
- **macOS:** CoreAudio/AudioQueue physical input.
- **Linux:** PipeWire/PipeWire-Pulse capture.
- **Never feeds:** an output bus directly.

### `BUS_REMOTE_CONFERENCE`

- **Source:** conference/system output.
- **Consumer:** inbound translation pipeline.
- **Windows:** WASAPI render-endpoint loopback.
- **macOS:** macOS 14.2+ Core Audio process tap scoped through a private aggregate device.
- **Linux:** PipeWire/Pulse sink monitor.
- **Never feeds:** the virtual microphone directly.

### `BUS_OUTBOUND_TRANSLATED_TTS`

- **Source:** translated TTS generated for the remote participant.
- **Consumer:** the platform virtual translation sink.
- **Never feeds:** the local monitor or inbound capture path.

### `BUS_INBOUND_TRANSLATED_TTS`

- **Source:** translated TTS generated for the local user.
- **Consumer:** `BUS_LOCAL_MONITOR`.
- **Never feeds:** the virtual microphone.

### `BUS_VIRTUAL_MIC`

- **Source:** platform `VoxPassport Translation Sink` through the bounded virtual cable.
- **Consumer:** `VoxPassport Virtual Microphone`, selected by Meet/Zoom/Teams/Discord/etc.

VoxPassport owns this virtual pair on every desktop platform; no third-party VB-Cable dependency is part of the core architecture.

### `BUS_LOCAL_MONITOR`

- **Source:** inbound translated TTS.
- **Consumer:** local headphones/speakers.
- **Requirement:** should not be selected as the system/conference capture source in a way that recursively re-enters the inbound translation path.

## Platform virtual-cable implementations

### Windows

```text
Translated PCM
    ↓
VoxPassport Translation Sink       (WDM render endpoint)
    ↓
64 KiB bounded kernel PCM ring
    ↓
VoxPassport Virtual Microphone     (WDM capture endpoint)
    ↓
Conference microphone selector
```

The driver is derived from a pinned Microsoft Simple Audio Sample substrate. Hosted Windows CI compiles and stages the WDK package. Physical installation and conferencing validation still require the target Windows machine.

### macOS

```text
Translated PCM
    ↓
VoxPassport Translation Sink       (HAL output device)
    ↓
64 KiB bounded PCM ring
    ↓
VoxPassport Virtual Microphone     (HAL input device)
    ↓
Conference microphone selector
```

The HAL driver is a real `AudioServerPlugIn` using libASPL. Hosted macOS CI installs it, restarts Core Audio, enumerates both endpoints, and validates deterministic PCM crossover.

### Linux

```text
Translated PCM
    ↓
VoxPassport Translation Sink       (PipeWire-Pulse null sink)
    ↓
monitor source
    ↓
VoxPassport Virtual Microphone     (remapped source)
    ↓
Conference microphone selector
```

A headless Ubuntu workflow starts PipeWire, WirePlumber and PipeWire-Pulse and validates live deterministic crossover through the native helper.

## Native media contract

The Python runtime communicates with the platform helper through `voxpassport.native-audio.v1` and binary `VPF1` PCM frames. Raw audio is intentionally excluded from Expo/React state, REST JSON, and base64 UI traffic.

The runtime persists stable endpoint IDs for:

- physical microphone;
- conference/system capture source;
- local monitor output;
- virtual render side;
- virtual capture side.

## Sample-rate policy

The virtual cable is fixed at:

- **48 kHz**;
- **signed 16-bit little endian**;
- **stereo**.

Model/provider audio may use different native shapes. Platform helpers normalize at the native boundary before rendering into the virtual cable.

Typical examples:

| Stage | Typical shape |
| --- | --- |
| ASR input | 16 kHz mono |
| Translation | text |
| TTS/provider output | model/provider native, commonly 24 kHz mono or another PCM shape |
| VoxPassport virtual cable | 48 kHz S16 stereo |
| Local monitor | output-device/native render shape |

**Rule:** resample only at explicit model/native-output boundaries. Do not repeatedly resample the same stream through multiple layers.

## Backpressure and latency

Capture/render queues are bounded. The virtual driver rings are also bounded. When a producer outruns a consumer, stale complete frames are dropped rather than allowing unbounded translated-speech latency to accumulate. Underflow produces silence.

## Feedback/recursion ownership

The routing design prevents the most obvious recursive paths structurally:

1. outbound translated TTS goes only to the virtual microphone path;
2. inbound translated TTS goes only to the local monitor;
3. the virtual microphone is not a valid inbound conference/system-capture source;
4. the local monitor should be excluded from the selected conference capture path where the platform/session topology permits it;
5. full acceptance requires real conferencing validation because speaker acoustics, application routing, echo cancellation, and OS mixing can still create physical feedback paths.

For final acceptance, validate with headphones first, then test the intended speaker/microphone topology in the actual conferencing application.
