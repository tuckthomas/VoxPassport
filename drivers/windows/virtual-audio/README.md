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

The bridge is deliberately bounded to 64 KiB. At the driver's 48 kHz / 16-bit / stereo PCM format that is about 341 ms. When the producer outruns the consumer, the oldest complete PCM frames are discarded so stale translated speech does not build an unbounded latency queue. Capture underflow produces silence.

## Microsoft substrate and licensing

The build is based on Microsoft's **Simple Audio Sample** from `microsoft/Windows-driver-samples`, pinned in `upstream.json`. The Microsoft source is not vendored into this repository. `prepare.ps1` downloads that exact commit, copies the Simple Audio Sample into `.work/`, preserves Microsoft's MS-PL license, and applies the VoxPassport-owned overlay and guarded source transformations.

If any pinned Microsoft source marker no longer matches exactly, preparation fails rather than silently creating a different driver.

Generated Microsoft/derivative source and packages live under ignored `.work/` and `out/` directories.

## Requirements

On the Windows validation/development machine:

- Visual Studio 2022 or Build Tools with Desktop C++ workload.
- Windows Driver Kit (WDK) integrated with Visual Studio.
- WDK Tools / `devcon.exe` for root-device test installation.
- Administrator PowerShell for installation/removal.
- Windows policy that permits the development/test-signed driver. `install-test.ps1` can request TESTSIGNING, but it never modifies Secure Boot settings.

## Prepare

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\prepare.ps1
```

Use `-Force` to discard the cached upstream archive/extraction and download the pinned source again. Ordinary reruns are idempotent: the patched tree is rebuilt from the pristine cached upstream extraction every time.

Preparation performs these guarded changes:

- adds `vp_audio_bridge.cpp/.h` to the WDM driver;
- routes speaker/render DMA PCM into the bounded ring bridge;
- routes microphone/capture DMA from that bridge instead of the sample's synthetic sine generator;
- changes the sample capture format from 48 kHz / 32-bit / stereo to 48 kHz / 16-bit / stereo so render and capture use the same PCM representation;
- changes the root hardware ID to `ROOT\VoxPassportVirtualAudio`;
- names the render endpoint `VoxPassport Translation Sink`;
- names the capture endpoint `VoxPassport Virtual Microphone`.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\build.ps1 -Configuration Debug -Platform x64
```

The script:

1. prepares a fresh patched tree;
2. locates MSBuild using `vswhere.exe` or `PATH`;
3. verifies the Windows Kits/WDK tree exists;
4. builds the pinned `SimpleAudioSample.sln`;
5. stages the generated INF/SYS/CAT package and Microsoft license under `drivers/windows/virtual-audio/out/x64/Debug/`.

A successful source build is not the same thing as a driver that Windows will load. Windows driver-signing policy still applies.

## Test install

Run elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\install-test.ps1
```

If the machine is intentionally configured for driver development and TESTSIGNING must be enabled:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\install-test.ps1 -EnableTestSigning
```

`-EnableTestSigning` only runs `bcdedit /set testsigning on`. It does **not** disable or alter Secure Boot. A reboot may be required before Windows will accept the development driver.

## Prove the cable actually works

After installation, first build the existing native helper if needed:

```powershell
cargo build --manifest-path crates\audio-windows\Cargo.toml --bin voxpassport-audio-helper --release
```

Then run:

```powershell
.venv\Scripts\python.exe scripts\validate_virtual_audio.py
```

The validator does not pass merely because the endpoints exist. It:

1. resolves the stable MMDevice IDs for `VoxPassport Translation Sink` and `VoxPassport Virtual Microphone`;
2. starts capture from the virtual microphone;
3. renders a deterministic 440 Hz PCM signal into the translation sink;
4. measures the PCM returned by the capture endpoint;
5. fails if the captured signal remains silent or insufficient data crosses the bridge.

Only after this test succeeds, and then the capture endpoint is successfully selected as a microphone in a real conferencing application, should the runtime's `virtual_microphone_validated` flag be confirmed.

## Remove development device

From elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\uninstall-test.ps1
```

This removes the root-enumerated device. It intentionally does not aggressively delete matching packages from Driver Store during development.

## Production signing

The development scripts are for local validation. Distribution to normal Windows systems requires an appropriate production driver signing/release process. Do not distribute test certificates or private signing keys through this repository; `.gitignore` excludes common certificate/key formats.
