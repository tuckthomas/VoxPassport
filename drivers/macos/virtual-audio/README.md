# VoxPassport macOS CoreAudio and HAL implementation

VoxPassport's macOS desktop audio path has two native pieces behind the same `voxpassport.native-audio.v1` / `VPF1` media contract used on Windows and Linux.

## Components

### `native/macos/audio-helper`

The Swift CoreAudio helper owns:

- stable CoreAudio device UID enumeration;
- physical microphone capture;
- physical/local render output;
- macOS 14.2+ Core Audio process-tap system capture through a private aggregate device;
- direct CoreAudio device I/O for the VoxPassport HAL endpoints;
- native PCM normalization before rendering into the fixed virtual-cable format.

Ordinary hardware paths use AudioQueue where appropriate. The VoxPassport virtual endpoints use direct device I/O because that is the reliable path for the custom HAL devices.

### `drivers/macos/virtual-audio`

The HAL `AudioServerPlugIn` publishes two real system devices:

- `VoxPassport Translation Sink`;
- `VoxPassport Virtual Microphone`.

The endpoints share a bounded 64 KiB realtime-safe PCM ring. Overflow drops the oldest complete stereo frames; underflow returns silence.

The plug-in uses libASPL as an AudioServerPlugIn interface shim. CMake fetches the pinned libASPL commit `633e0f70203edd87d320fc5a3cae901e1363aac5`; the dependency is not vendored.

## Fixed cable format

The HAL cable is fixed at:

- 48 kHz;
- signed 16-bit little endian;
- stereo.

Provider output can use another shape. The helper normalizes provider/native PCM at the native boundary before writing to the HAL sink. Hosted CI specifically exercises provider-style 24 kHz mono input into the fixed 48 kHz stereo cable.

## Build

```bash
swift build --package-path native/macos/audio-helper -c release
cmake -S drivers/macos/virtual-audio -B drivers/macos/virtual-audio/build -DCMAKE_BUILD_TYPE=Release
cmake --build drivers/macos/virtual-audio/build --config Release
```

## Install virtual devices

```bash
./drivers/macos/virtual-audio/install.sh
```

Installation copies `VoxPassportVirtualAudio.driver` to:

```text
/Library/Audio/Plug-Ins/HAL/VoxPassportVirtualAudio.driver
```

and restarts Core Audio. The script does not weaken Gatekeeper or invent a signing identity. Production distribution requires an appropriate signing/notarization workflow.

## Validate

```bash
native/macos/audio-helper/.build/release/voxpassport-audio-helper probe
native/macos/audio-helper/.build/release/voxpassport-audio-helper devices
python3 scripts/validate_macos_virtual_audio.py
```

The deterministic validator uses the native helper itself. It:

1. resolves the exact translation-sink and virtual-microphone UIDs;
2. starts capture from `VoxPassport Virtual Microphone`;
3. renders deterministic 440 Hz provider-shape PCM into `VoxPassport Translation Sink`;
4. captures returned PCM from the HAL microphone;
5. locates the strongest coherent tone window;
6. rejects silence, insufficient data, or a missing expected 440 Hz component.

## Hosted validation status

GitHub's hosted macOS runner currently validates the complete source-level virtual-device path:

- Swift helper compile;
- HAL CMake configure/build;
- install into `/Library/Audio/Plug-Ins/HAL`;
- Core Audio restart;
- enumeration of both VoxPassport endpoints;
- deterministic real PCM crossover through the HAL ring;
- provider-shape PCM normalization into the fixed cable format;
- clean uninstall.

So HAL installation/enumeration/crossover are **not** waiting for a physical Mac.

## What still requires a physical Mac

A real Mac is still required to validate:

- actual built-in/USB microphone and output-device behavior;
- real user TCC/system-audio recording permission prompts;
- the chosen conferencing application's device selection/behavior;
- real acoustic echo/feedback topology;
- production code signing/notarization/distribution policy.

System-output capture requires macOS 14.2+ plus the applicable privacy permission.

## Uninstall

```bash
./drivers/macos/virtual-audio/uninstall.sh
```

This removes the HAL bundle and restarts Core Audio.
