# VoxPassport Windows Virtual Audio Cable

This directory owns the Windows virtual-microphone build pipeline used by the desktop VoxPassport runtime.

## Architecture

The user-mode runtime never pretends an ordinary render endpoint is a microphone. The installed driver exposes a real Windows render/capture pair:

```text
VoxPassport translated PCM
        |
        v
VoxPassport Translation Sink          (Windows render endpoint)
        |
        v
bounded kernel PCM ring bridge
        |
        v
VoxPassport Virtual Microphone        (Windows capture endpoint)
        |
        v
Meet / Zoom / Teams / Discord / softphone microphone selector
```

The bridge is deliberately bounded to 64 KiB. At 48 kHz / signed 16-bit / stereo that is about 341 ms. When the producer outruns the consumer, the oldest complete PCM frames are discarded so stale translated speech cannot create an unbounded latency queue. Capture underflow produces silence.

## Microsoft substrate and licensing

The build is based on Microsoft's **Simple Audio Sample** from `microsoft/Windows-driver-samples`, pinned in `upstream.json`. The Microsoft source is not vendored into this repository.

`prepare.ps1`:

1. downloads the exact pinned Microsoft commit;
2. copies the Simple Audio Sample into ignored `.work/` state;
3. preserves Microsoft's MS-PL license;
4. adds the VoxPassport PCM ring bridge;
5. applies guarded source/INF/format transformations.

If an expected upstream marker no longer matches exactly, preparation fails rather than silently creating a different derivative.

## Validation status

Hosted Windows CI now performs the complete source-level build path:

- validates the PowerShell scripts;
- prepares the pinned Microsoft substrate;
- verifies guarded VoxPassport patches, endpoint names and preserved license;
- installs the current WDK on the hosted runner;
- restores the current Microsoft WDK/SDK NuGet build packages;
- compiles the WDM kernel driver;
- validates the generated package with architecture-correct WDK tooling;
- stages and verifies `SimpleAudioSample.inf` and `SimpleAudioSample.sys`;
- runs the portable and Windows Rust native-audio tests.

This means **WDK compilation/staging is CI-validated**. It does not mean Windows on an arbitrary target PC will load the development package: driver installation policy and physical audio behavior remain machine-specific acceptance steps.

## Local build requirements

For a local Windows development/validation machine:

- Visual Studio or Visual Studio Build Tools with MSBuild and the Desktop C++ workload;
- Windows Driver Kit (WDK), or an environment where the build script can restore the supported WDK/SDK NuGet packages;
- WDK Tools / `devcon.exe` for root-device test installation;
- Administrator PowerShell for installation/removal;
- Windows policy that permits the development/test-signed driver.

`install-test.ps1` can request TESTSIGNING, but it never disables or modifies Secure Boot.

## Prepare

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\prepare.ps1
```

Use `-Force` to discard cached upstream archive/extraction state and download the pinned source again. Normal reruns rebuild the patched tree from the pristine cached source and are idempotent.

Preparation performs these guarded changes:

- adds `vp_audio_bridge.cpp/.h` to the WDM driver;
- routes render DMA PCM into the bounded ring bridge;
- routes capture DMA from that bridge instead of the Microsoft sample's synthetic sine generator;
- normalizes the sample capture side to 48 kHz / 16-bit / stereo so render and capture use the same representation;
- changes the root hardware ID to `ROOT\VoxPassportVirtualAudio`;
- names the render endpoint `VoxPassport Translation Sink`;
- names the capture endpoint `VoxPassport Virtual Microphone`.

## Build

Debug:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\build.ps1 -Configuration Debug -Platform x64
```

Release:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\build.ps1 -Configuration Release -Platform x64
```

The build script prepares the source, restores WDK/SDK packages when available, locates MSBuild, builds the pinned solution, runs architecture-correct WDK package validation, and stages the resulting package under:

```text
drivers/windows/virtual-audio/out/x64/<Configuration>/
```

The staged directory includes the INF/SYS package, preserved Microsoft license, and VoxPassport upstream metadata.

A successful build is not the same thing as a driver accepted by the target machine's signing policy.

## Test install on the physical Windows machine

Run elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\install-test.ps1
```

If the machine is intentionally configured for driver development and TESTSIGNING must be enabled:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\install-test.ps1 -EnableTestSigning
```

`-EnableTestSigning` runs only:

```text
bcdedit /set testsigning on
```

It does **not** alter Secure Boot. A reboot may be required before Windows reports TESTSIGNING as active.

## Prove the cable actually works

After installation, build the native helper if needed:

```powershell
cargo build --manifest-path crates\audio-windows\Cargo.toml --bin voxpassport-audio-helper --release
```

Then run:

```powershell
.venv\Scripts\python.exe scripts\validate_virtual_audio.py
```

The validator does not pass merely because the endpoints exist. It:

1. resolves stable MMDevice IDs for `VoxPassport Translation Sink` and `VoxPassport Virtual Microphone`;
2. starts capture from the virtual microphone;
3. renders deterministic 440 Hz PCM into the translation sink;
4. captures the resulting PCM;
5. fails for silence, insufficient data, or missing expected signal.

Only after this succeeds should the virtual microphone be selected in a real conferencing application for full routing/echo acceptance.

## Physical acceptance still required

Hosted CI cannot prove:

- target-PC driver-policy acceptance;
- physical microphone endpoint formats;
- real WASAPI hardware capture/render behavior;
- actual conference application selection;
- speaker/microphone acoustic feedback behavior.

Those checks belong on the development Windows machine after pulling the green CI build.

## Remove development device

From elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\uninstall-test.ps1
```

This removes the root-enumerated device. It intentionally does not aggressively remove matching packages from Driver Store during development.

## Production signing

The development scripts are for source/physical validation. Distribution to ordinary Windows systems requires an appropriate production driver signing and release process. Do not commit or distribute test certificates/private signing keys through this repository; `.gitignore` excludes common certificate/key formats.
