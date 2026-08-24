# VoxPassport PipeWire virtual microphone

Linux does not require a kernel audio driver for the VoxPassport conferencing path. This directory installs a persistent PipeWire-Pulse virtual cable with the same endpoint names and media contract used on Windows:

```text
translated PCM
  -> VoxPassport Translation Sink
  -> sink monitor
  -> VoxPassport Virtual Microphone
  -> Meet / Zoom / Teams / Discord microphone selector
```

The configuration uses PipeWire's PulseAudio compatibility server because `module-null-sink` and `module-remap-source` provide a stable, widely supported way to publish a render sink plus microphone source. Realtime application audio still uses PipeWire's native `pw-record` and `pw-play` clients through `crates/audio-linux`; PulseAudio compatibility is only the endpoint/configuration layer.

## Requirements

- Linux desktop session with PipeWire and PipeWire-Pulse running.
- `pw-record`, `pw-play`, and `pactl` on `PATH`.
- On Ubuntu these normally come from the PipeWire tools and PulseAudio utilities packages.
- WSL alone does not guarantee an audio server. WSLg or a separately configured PipeWire-Pulse session is required before the live endpoint test can pass.

## Install

```bash
./drivers/linux/virtual-audio/install.sh
```

The script writes:

`~/.config/pipewire/pipewire-pulse.conf.d/90-voxpassport-virtual-audio.conf`

It also attempts to load the two modules into the current PipeWire-Pulse session so a logout is normally unnecessary. The persistent config is authoritative across future PipeWire-Pulse restarts.

## Validate

Build the Linux native helper:

```bash
cargo build --manifest-path crates/audio-linux/Cargo.toml --release
```

Confirm the endpoints enumerate:

```bash
./crates/target/release/voxpassport-audio-helper probe
./crates/target/release/voxpassport-audio-helper devices
```

Then run the deterministic cable test:

```bash
python scripts/validate_pipewire_virtual_audio.py
```

The validator records the virtual microphone, renders deterministic 440 Hz PCM to the translation sink, and rejects silence or an obviously missing 440 Hz component.

## Uninstall

```bash
./drivers/linux/virtual-audio/uninstall.sh
```

This removes the persistent config and unloads currently active VoxPassport Pulse modules when possible.

## Fixed virtual-cable format

The installed virtual pair is 48 kHz, signed 16-bit little-endian, stereo. Provider output may use another shape; the native media layer is responsible for opening/rendering the negotiated output shape. The virtual endpoint itself stays fixed so conferencing applications see a predictable device.
