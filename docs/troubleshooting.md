# VoxPassport Troubleshooting

## Start with the correct local topology

For normal Windows development, use:

```bat
install.bat
run.bat
```

Expected services:

| Service | Address |
| --- | --- |
| Canonical Expo web client | `http://127.0.0.1:8081` |
| Integrated runtime/API | `http://127.0.0.1:8766` |
| Caption WebSocket | `ws://127.0.0.1:8765/ws/captions` |

The retired HTML Studio/model-manager and `apps/desktop-companion` are no longer part of the runtime.

For personal/local use, the root `.env` should normally contain:

```env
VOXPASSPORT_LOCAL_ONLY=true
```

That disables account/login/signup requirements and hosted abuse controls.

---

# Native audio troubleshooting

## First diagnostic: probe the native helper

The platform helper must be discoverable and able to enumerate endpoints before debugging inference.

### Windows

```powershell
cargo build --manifest-path crates\audio-windows\Cargo.toml --bin voxpassport-audio-helper --release
crates\target\release\voxpassport-audio-helper.exe probe
crates\target\release\voxpassport-audio-helper.exe devices
```

### Linux

```bash
cargo build --manifest-path crates/audio-linux/Cargo.toml --release
./crates/target/release/voxpassport-audio-helper probe
./crates/target/release/voxpassport-audio-helper devices
```

### macOS

```bash
swift build --package-path native/macos/audio-helper -c release
native/macos/audio-helper/.build/release/voxpassport-audio-helper probe
native/macos/audio-helper/.build/release/voxpassport-audio-helper devices
```

If the Python runtime cannot discover a helper built in a nonstandard location, set `VOXPASSPORT_AUDIO_HELPER` explicitly.

## Virtual microphone exists but has no signal

Separate virtual-cable validation from inference.

### Windows

After the driver is installed:

```powershell
.venv\Scripts\python.exe scripts\validate_virtual_audio.py
```

### macOS

After the HAL plug-in is installed:

```bash
python3 scripts/validate_macos_virtual_audio.py
```

### Linux

After the virtual pair is installed:

```bash
python scripts/validate_pipewire_virtual_audio.py
```

Each validator injects deterministic PCM into `VoxPassport Translation Sink`, records from `VoxPassport Virtual Microphone`, and requires measurable expected signal. If this fails, fix the platform audio path before debugging ASR/translation/TTS.

## Windows driver will not install

Hosted CI proves WDK preparation/compile/staging but does not override the target machine's driver policy.

Build:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\build.ps1 -Configuration Release -Platform x64
```

Install from elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File drivers\windows\virtual-audio\install-test.ps1
```

For an intentionally configured driver-development machine, `-EnableTestSigning` may request Windows TESTSIGNING. The script does not modify Secure Boot.

If installation fails, check:

- PowerShell is elevated;
- `devcon.exe` is available from WDK Tools;
- the staged INF/SYS/CAT package exists;
- the machine's Secure Boot/test-signing policy permits the development package;
- a reboot was performed if Windows required it after changing TESTSIGNING state.

## Windows endpoints enumerate but real capture/render fails

Hosted CI cannot validate your physical audio hardware/driver format negotiation. On the target machine:

1. run the native helper `devices` command;
2. confirm the stable MMDevice ID corresponds to the intended physical device;
3. test physical microphone capture independently;
4. test conference render-endpoint loopback independently;
5. test local render independently;
6. only then start full-duplex inference.

## Linux helper cannot connect to audio

The Linux helper requires an active PipeWire/PipeWire-Pulse session.

Check:

```bash
pactl info
pw-dump >/dev/null
systemctl --user status pipewire pipewire-pulse wireplumber
```

WSL by itself does not guarantee an audio server. WSLg or a separately configured PipeWire/PipeWire-Pulse environment is required for live audio tests.

Install the VoxPassport virtual pair with:

```bash
./drivers/linux/virtual-audio/install.sh
```

Then confirm both exact names appear:

- `VoxPassport Translation Sink`
- `VoxPassport Virtual Microphone`

## macOS helper builds but physical system capture fails

Hosted CI validates the HAL virtual pair but not your physical Mac permissions.

For real system-audio capture:

- macOS 14.2+ is required for the Core Audio process-tap path;
- the application/helper must receive the applicable TCC privacy permission;
- real physical microphone/output UIDs must enumerate correctly;
- production distribution requires appropriate signing/notarization.

Do not interpret hosted HAL crossover success as proof that a specific user's TCC/hardware topology is accepted.

## Conference application hears original speech instead of translation

The conference application is probably still using the physical microphone.

Select:

```text
VoxPassport Virtual Microphone
```

as the meeting microphone. Keep the normal headphones/speakers as the meeting output device.

## Feedback / recursive translation

Start with headphones.

Verify:

- outbound translated TTS routes only to `VoxPassport Translation Sink`;
- inbound translated TTS routes only to the local monitor;
- the virtual microphone is not selected as inbound/system capture;
- the local monitor is not being captured as the conference source;
- speaker acoustics are not feeding translated playback back into the physical mic.

Physical conference routing is an acceptance test; CI cannot prove acoustic feedback behavior.

See [`audio-routing.md`](audio-routing.md) and [`google-meet-integration.md`](google-meet-integration.md).

---

# Expo/client troubleshooting

## Expo client will not start

Run:

```bat
install.bat
```

or install client dependencies directly:

```bash
npm install --prefix apps/client
```

Then:

```bash
npm run --prefix apps/client typecheck
npm run --prefix apps/client export:web
```

CI runs both typecheck and static web export.

## UI says the runtime is offline

Confirm the integrated runtime is listening on `127.0.0.1:8766` and the selected runtime target URL is correct.

The Expo client must use the typed runtime-target/API abstraction; do not reintroduce hard-coded fetch interception or legacy manager URLs.

## Login/signup pages appear in local-only mode

Confirm:

```env
VOXPASSPORT_LOCAL_ONLY=true
```

and restart the runtime/client. The runtime bootstrap capability response controls whether account surfaces are available.

---

# Model installation and activation

## Model cannot be installed

The backend catalog/API owns installability.

Inspect `installable` and `installation_reason` in the model response. Typical reasons include:

- already installed;
- installation already in progress;
- no verified official downloadable repository configured for the catalog entry.

Do not work around this by adding model-name exceptions in the Expo UI.

## Model downloads but cannot become active

Installation and runtime-adapter support are separate concerns. A downloaded model may not yet have an implemented production adapter for the requested capability.

Check the runtime activation error and verify the model family is supported by the relevant ASR/translation/TTS/VAD adapter.

## GPU out of memory

- select a lower-memory model/quantization where available;
- keep CPU-suitable translation/diarization components off GPU on constrained systems;
- do not keep multiple heavyweight TTS backends resident unnecessarily;
- verify a released managed backend actually terminated;
- distinguish model file size from runtime CUDA memory consumption.

---

# TTS runtime architecture diagnostics

Every local TTS model reaches the application through:

```text
TTS model manifest
  │ runtime_profile
  │ optional backend_runtime + backend_args
  ▼
TtsRuntimeSupervisor
  ├─ ephemeral generic worker
  └─ optional managed backend runtime
       ↓
ManifestTtsAdapter ↔ voxpassport.tts.v1
       ↓
TtsDriver
```

The main daemon should not import model-specific local TTS application adapters.

## TTS model appears but will not load

1. Confirm its manifest exists under `runtime/tts_manifests/`.
2. Check the manifest's worker `runtime_profile`.
3. If it declares `backend_runtime`, confirm that runtime exists under `runtime/tts_backend_runtimes/` and required `backend_args` are present.
4. Verify the required runtime profile is installed.
5. Inspect `data/logs/tts-worker-<profile>.log`.
6. For managed backends, inspect `data/logs/tts-backend-<backend-runtime>-<model-id>.log`.
7. Verify model/checkpoint assets are complete.

## Runtime profile is missing

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

For `coqui-xtts`, the isolated environment lives under:

```text
runtime/profiles/coqui-xtts/.venv
```

Do not recreate the retired root-level `.venv-xtts` topology.

## Backend runtime is unknown

The model manifest references a `backend_runtime` ID that is not registered under `runtime/tts_backend_runtimes/`.

Fix the runtime ID or add one reusable backend-family definition. Do not add a model-name branch to the supervisor.

## Required backend argument is missing

The backend runtime contract requires an argument such as `checkpoint`, but the model manifest did not supply it under `backend_args`.

Validation should fail before synthesis begins.

## No backend-family launch command is configured

Configure the backend server family once rather than creating a per-model command variable. Existing deployment-level family overrides include:

```text
VOXPASSPORT_TTS_BACKEND_HIGGS_COMMAND
VOXPASSPORT_TTS_BACKEND_MOSS_COMMAND
VOXPASSPORT_TTS_BACKEND_VOXCPM_COMMAND
```

Explicit non-loopback remote backend URLs may replace local launch. Unmanaged loopback GPU backends are intentionally rejected because they would sit outside supervisor residency ownership.

## Managed backend remains in VRAM after switching

That is a bug for supervisor-owned local backends. Switching/releasing the model must terminate the complete managed backend process tree when it is no longer the active residency owner.

Check the runtime diagnostics and `nvidia-smi`.

## Worker dies during synthesis

If failure occurs before any PCM is emitted, the adapter may recreate the supervised runtime and retry once. If speech was already partially emitted, VoxPassport does not automatically replay the utterance.

## Voice profile works in one TTS model but not another

Voice profiles are model-independent; model capabilities are not.

Check:

- whether the selected manifest requires an exact reference transcript;
- target-language support;
- cross-lingual cloning support;
- reference audio quality;
- backend/worker health.

---

# Runtime integrity and CI

GitHub CI currently validates:

- Python compile/runtime routing tests;
- account-service/PostgreSQL migrations and integration tests;
- Expo TypeScript typecheck/export;
- Windows WDK driver compile and staged INF/SYS verification;
- Windows Rust audio/helper tests;
- Linux Rust helper tests;
- headless live Linux PipeWire virtual-cable crossover;
- macOS Swift helper and HAL build;
- hosted macOS HAL install/enumeration/crossover/uninstall.

Useful local Python checks include:

```bat
.venv\Scripts\python.exe -m compileall -q runtime agents tests benchmarks scripts
.venv\Scripts\python.exe -m pytest -q tests
```

A green hosted run proves source/build and hosted virtual-media behavior. Real Windows hardware/driver-policy/conferencing acceptance and real Mac TCC/hardware behavior remain separate validation stages.
