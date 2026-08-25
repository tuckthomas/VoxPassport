# VoxPassport Linux PipeWire virtual microphone

Linux does not require a kernel audio driver for the VoxPassport conferencing path. The Linux implementation uses a persistent PipeWire-Pulse virtual cable plus a Rust native helper behind the same `voxpassport.native-audio.v1` / `VPF1` media contract used on Windows and macOS.

```text
translated PCM
  -> VoxPassport Translation Sink
  -> sink monitor
  -> VoxPassport Virtual Microphone
  -> Meet / Zoom / Teams / Discord microphone selector
```

## Components

### `crates/audio-linux`

The Rust helper owns:

- endpoint discovery through PipeWire-Pulse metadata;
- stable classification of physical microphones, render sinks, and sink-monitor loopback sources;
- physical microphone capture;
- conference/system capture through sink monitors;
- translated/local render output;
- bounded native capture/render queues.

The helper uses the Pulse-compatible clients for exact endpoint targeting against the PipeWire-Pulse virtual modules. This avoids version-specific `pw-play`/`pw-record` target behavior while the desktop audio server remains PipeWire.

### `drivers/linux/virtual-audio`

The persistent virtual pair uses PipeWire's PulseAudio compatibility server:

- `module-null-sink` publishes `VoxPassport Translation Sink`;
- the sink monitor carries rendered PCM;
- `module-remap-source` publishes `VoxPassport Virtual Microphone`.

This gives conferencing applications a normal render sink plus a normal microphone source without a kernel module.

## Requirements

- Linux desktop/session with PipeWire and PipeWire-Pulse running;
- WirePlumber or another PipeWire session manager;
- `pactl`, `paplay`, and `parec` on `PATH`;
- PipeWire utilities such as `pw-dump` are recommended for diagnostics.

WSL alone does not guarantee an audio server. WSLg or a separately configured PipeWire/PipeWire-Pulse session is required for live endpoint testing.

## Install

```bash
./drivers/linux/virtual-audio/install.sh
```

The installer writes:

```text
~/.config/pipewire/pipewire-pulse.conf.d/90-voxpassport-virtual-audio.conf
```

It also attempts to load the two modules into the current session so a logout/restart is normally unnecessary. The persistent configuration remains authoritative across future PipeWire-Pulse restarts.

## Build the native helper

```bash
cargo build --manifest-path crates/audio-linux/Cargo.toml --release
```

## Confirm endpoint discovery

```bash
./crates/target/release/voxpassport-audio-helper probe
./crates/target/release/voxpassport-audio-helper devices
```

Expected exact endpoint names:

- `VoxPassport Translation Sink`
- `VoxPassport Virtual Microphone`

## Deterministic cable validation

```bash
python scripts/validate_pipewire_virtual_audio.py
```

The validator exercises the VoxPassport helper/media boundary, not merely a third-party client. It captures the virtual microphone, renders realtime-paced deterministic 440 Hz PCM into the translation sink, and rejects silence, insufficient data, or a missing expected 440 Hz component.

## Hosted validation status

The dedicated Linux live-validation workflow starts a headless audio session consisting of:

```text
D-Bus
  ↓
PipeWire
  ↓
WirePlumber
  ↓
PipeWire-Pulse
  ↓
VoxPassport virtual pair
```

It then builds the Rust helper, installs the virtual pair and runs deterministic sink→virtual-microphone PCM crossover. That hosted live path is green.

This is stronger than compile-only validation, but distribution-specific desktop/conferencing behavior should still be checked on the intended Linux/WSLg environment.

## Fixed virtual-cable format

The installed virtual pair is:

- 48 kHz;
- signed 16-bit little endian;
- stereo.

Provider/native audio may use another shape; the native media layer owns conversion/render negotiation before the system-facing virtual endpoint.

## Diagnostics

Useful commands:

```bash
pactl info
pactl list short sinks
pactl list short sources
pw-dump >/dev/null
systemctl --user status pipewire pipewire-pulse wireplumber
```

If the helper reports no devices, first confirm PipeWire-Pulse is reachable. If the virtual pair is absent, rerun the installer and inspect the generated PipeWire-Pulse configuration.

## Uninstall

```bash
./drivers/linux/virtual-audio/uninstall.sh
```

This removes the persistent configuration and unloads active VoxPassport Pulse modules when possible.
