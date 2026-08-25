# Google Meet and Conferencing Integration

## Core integration: OS virtual microphone

VoxPassport does not require a Google Meet API to translate audio.

The core conferencing path is platform-independent at the product level:

1. capture the local physical microphone through the native audio helper;
2. translate/synthesize speech in the local runtime or selected direct provider;
3. render translated PCM into `VoxPassport Translation Sink`;
4. the platform virtual cable exposes that PCM through `VoxPassport Virtual Microphone`;
5. select `VoxPassport Virtual Microphone` as the microphone in Google Meet, Zoom, Teams, Discord, Webex, or another conferencing application;
6. capture conference/system output separately for the inbound translation direction;
7. route inbound translated speech only to the local monitor.

No third-party VB-Cable installation is part of the intended VoxPassport architecture.

## Platform implementation

| Platform | Conference/system capture | Virtual microphone implementation |
| --- | --- | --- |
| Windows | WASAPI loopback from the selected render endpoint | VoxPassport WDM/WDK render/capture pair with bounded kernel PCM ring |
| macOS | macOS 14.2+ Core Audio process tap | VoxPassport HAL `AudioServerPlugIn` render/capture pair |
| Linux | PipeWire/Pulse sink monitor | PipeWire-Pulse null sink + remapped virtual source |

The system-facing endpoint names are intentionally consistent:

- `VoxPassport Translation Sink`
- `VoxPassport Virtual Microphone`

## Recommended Google Meet setup

1. Start VoxPassport and confirm the native audio helper reports the intended physical microphone, conference/system capture source, local monitor, and both virtual endpoints.
2. In Google Meet **Microphone**, select `VoxPassport Virtual Microphone`.
3. Keep the normal headphones/speakers as the Meet speaker/output device.
4. In VoxPassport, select the corresponding conference/system output for inbound capture.
5. Start in **Outbound** mode and verify a translated test phrase is received remotely.
6. Enable **Inbound** and then **Full Duplex** only after one-way routing works.
7. Validate feedback/echo ownership in the real meeting topology.

Headphones are the safest initial validation topology because they minimize acoustic feedback while routing is being verified.

## Expected routing

```text
LOCAL → REMOTE
Physical Mic
   ↓
VoxPassport outbound translation
   ↓
Translation Sink
   ↓
Virtual Microphone
   ↓
Google Meet microphone input

REMOTE → LOCAL
Google Meet speaker/output
   ↓
OS system/loopback capture
   ↓
VoxPassport inbound translation
   ↓
Local monitor/headphones
```

The inbound translated result must never be intentionally routed back into the virtual microphone.

## Common routing errors

| Symptom | Likely problem |
| --- | --- |
| Remote participant hears the original local language | Meet is still using the physical microphone instead of `VoxPassport Virtual Microphone` |
| Remote participant hears nothing | Translation Sink/Virtual Microphone path is not installed/configured, TTS/direct-provider output is not being rendered, or Meet is using another input |
| Local user hears no inbound translation | Wrong system/loopback source or wrong local monitor output |
| Repeated/retranslated speech | Virtual/local monitor output is being recaptured or acoustic feedback is entering a physical microphone |
| Virtual microphone exists but carries silence | Run the deterministic platform cable validator before debugging inference |

## Deterministic cable validation comes first

Before blaming Meet or the inference stack, validate the platform cable itself.

### Windows

```powershell
.venv\Scripts\python.exe scripts\validate_virtual_audio.py
```

### macOS

```bash
python3 scripts/validate_macos_virtual_audio.py
```

### Linux

```bash
python scripts/validate_pipewire_virtual_audio.py
```

These validators render known PCM into the translation sink and require corresponding signal from the virtual microphone. Passing the validator proves the virtual cable path independently of Meet.

## Browser extension

`apps/browser-extension` is optional browser-specific integration. It can provide overlays/status/control conveniences, but it is not the core audio transport and must not become a second inference/runtime implementation.

The canonical UI remains `apps/client`.

## Meet Add-ons SDK

Meet add-ons are suitable for auxiliary UI experiences such as status or captions. They are not the foundation for VoxPassport's raw desktop audio capture/injection because the core product needs to remain conferencing-platform independent.

## Meet Media API / bot-style integration

A server/bot-style Meet Media API integration could be useful for future enterprise or participant-isolated workflows, but it is not required for the local desktop product. Such an approach introduces different authentication, infrastructure, participant-media, and network-latency concerns.

The current architectural decision remains:

> **OS-native system capture + VoxPassport virtual microphone is the core desktop conferencing transport.**

Provider selection is independent. The translated speech can come from the modular local cascade or a direct speech-translation provider without changing the Meet routing topology.

## Validation status

Hosted CI currently validates:

- Windows WDK virtual-driver compile and staged package creation;
- macOS HAL build/install/enumeration and deterministic PCM crossover;
- Linux headless PipeWire virtual-pair deterministic crossover.

Physical conferencing acceptance remains intentionally separate:

- Windows: install/test-sign under the target machine's policy, run the deterministic validator, then select the virtual microphone in a real conference.
- macOS: real hardware/TCC/conferencing and production signing/notarization still require a physical Mac.
- Linux: validate the target desktop distribution/session and the chosen conferencing application.
