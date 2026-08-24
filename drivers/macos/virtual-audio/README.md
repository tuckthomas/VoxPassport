# VoxPassport CoreAudio implementation

VoxPassport's macOS desktop audio path has two independent native pieces:

1. `native/macos/audio-helper` — a CoreAudio/AudioQueue command-line helper implementing the same `voxpassport.native-audio.v1` + `VPF1` subprocess protocol used on Windows and Linux. It enumerates stable CoreAudio device UIDs, captures physical microphones, renders translated PCM, and uses a macOS 14.2+ Core Audio process tap wrapped in a private aggregate device for system-output capture.
2. `drivers/macos/virtual-audio` — a HAL `AudioServerPlugIn` that publishes `VoxPassport Translation Sink` and `VoxPassport Virtual Microphone` as real system audio devices. The two endpoints share a bounded 64 KiB realtime-safe PCM ring. Overflow drops the oldest complete stereo PCM frames; underflow returns silence.

The virtual device uses libASPL as an AudioServerPlugIn interface shim. The dependency is not vendored: CMake fetches the pinned commit `633e0f70203edd87d320fc5a3cae901e1363aac5`.

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

Installation copies `VoxPassportVirtualAudio.driver` to `/Library/Audio/Plug-Ins/HAL` and restarts Core Audio. The script does not weaken Gatekeeper or invent a signing identity. For distributed production builds, provide an appropriate signing/notarization workflow.

## Validate

```bash
native/macos/audio-helper/.build/release/voxpassport-audio-helper probe
native/macos/audio-helper/.build/release/voxpassport-audio-helper devices
python scripts/validate_macos_virtual_audio.py
```

The deterministic validator uses the helper itself: it captures `VoxPassport Virtual Microphone`, renders a 440 Hz PCM signal into `VoxPassport Translation Sink`, and verifies that non-silent 440 Hz audio crossed the HAL plug-in ring.

System-output capture uses Apple's Core Audio process-tap APIs and therefore requires macOS 14.2 or newer plus the applicable system-audio recording privacy permission. Physical hardware, TCC prompts, installed HAL enumeration, and conferencing-application selection still require validation on an actual Mac.
