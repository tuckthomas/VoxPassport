# VoxPassport Privacy & Security

## Data-processing principles

1. **Local-first by default.** The reference modular pipeline can run entirely on the user's machine.
2. **Local-only is a first-class deployment.** `VOXPASSPORT_LOCAL_ONLY=true` disables account requirements and hosted abuse controls; local use does not require VoxPassport-hosted infrastructure.
3. **No transcript persistence by default.** Live transcripts/translations are not written to disk unless an explicit workflow saves them.
4. **No unattended audio recording.** Live audio is processed on realtime native/runtime paths and is not automatically persisted. Voice enrollment is an explicit recording/import workflow.
5. **Content-minimized diagnostics.** Metrics/logs should prefer model/runtime/status/timing information over conversation content.
6. **Explicit voice enrollment.** A reusable voice profile is created only through user action.
7. **Remote inference is explicit.** Off-device providers/workers are separate execution modes and should not be mistaken for VoxPassport-owned localhost worker processes.
8. **High-frequency PCM stays out of the UI/control plane.** Raw media is not transported through React state, REST JSON, base64 UI messages, or browser eval bridges.

## Local deployment boundary

For personal/local use:

```env
VOXPASSPORT_LOCAL_ONLY=true
```

In local-only mode:

- the Expo client hides account/login/signup surfaces based on runtime bootstrap capabilities;
- the local inference runtime remains the owner of models, voice profiles, inference and native audio routing;
- no PostgreSQL account service is required;
- provider API credentials can remain local environment/deployment configuration where applicable.

## Account-enabled deployments

When accounts are enabled, the separate account service owns identity/session/provider-credential state. Current security controls include:

- PostgreSQL 18.6 persistence;
- Argon2id password hashing;
- short-lived access JWTs;
- opaque rotating refresh tokens whose hashes—not raw tokens—are stored in PostgreSQL;
- HttpOnly refresh cookies for web;
- Expo SecureStore for native refresh-token storage;
- access tokens kept memory-only in the client;
- AES-GCM encryption for stored provider credentials;
- application-layer auth rate controls outside local-only mode.

Email verification, password-reset email/token delivery, OAuth/social identity and managed-cloud allocation remain deferred rather than being partially simulated.

## Voice profiles

A canonical local voice profile can contain:

```text
reference.wav
reference.txt            # optional unless the active TTS manifest requires it
profile.json
translated_sample.wav    # optional generated preview/sample
conditioning/...         # optional derived model-specific assets
```

The reference recording is canonical speaker material. Derived conditioning must never overwrite `reference.wav`.

The Expo client owns the explicit record/stage/preview/save/activate/delete UX. The runtime owns audio normalization, persistence, synthesis, preview caching and active-profile state.

## Voice-cloning safety boundary

- enrollment requires explicit user action;
- the active voice profile is visible/selectable in the product UI;
- profile deletion remains user-controlled;
- remote-participant diarization does not imply permission to clone another participant's voice;
- a selected TTS model's cloning/transcript/language capabilities govern whether a profile is usable;
- remote voice-profile transfer requires an explicit secure synchronization/enrollment design.

## Local TTS workers and backend runtimes

Local TTS uses supervisor-owned ephemeral localhost processes:

```text
ManifestTtsAdapter
    ↓
TtsRuntimeSupervisor
    ├── generic worker host → TtsDriver
    └── optional managed backend runtime
```

Runtime profiles are dependency-compatible environments such as:

```text
core
runtime/profiles/coqui-xtts/.venv
```

These workers/backends are local processes even though they communicate over localhost HTTP.

Security rules:

- bind local worker/backend endpoints to loopback;
- assign endpoints dynamically rather than exposing a fixed public service topology;
- do not expose local worker ports to LAN/WAN interfaces;
- keep process lifecycle under the supervisor;
- reject unmanaged loopback GPU backends that would escape local residency ownership;
- permit explicit non-loopback remote backends only as separately configured remote resources;
- minimize persistence of generated speech/transcripts unless the workflow requests it;
- keep private keys/test certificates out of the repository.

## Native desktop audio boundary

Platform helpers and virtual devices operate locally:

- Windows: WASAPI/MMDevice helper + WDM/WDK virtual cable;
- macOS: CoreAudio helper + HAL AudioServerPlugIn;
- Linux: PipeWire/PipeWire-Pulse helper + virtual sink/source.

The Python bridge exchanges binary `VPF1` PCM frames with the native helper. The Expo client sees low-frequency capability/device/session state rather than raw media.

Virtual microphone installation can have platform-specific privilege/signing implications:

- Windows development-driver installation depends on Windows signing/Secure Boot/test-signing policy;
- macOS HAL installation uses `/Library/Audio/Plug-Ins/HAL` and production distribution requires appropriate signing/notarization;
- Linux virtual endpoints are user-session PipeWire/PipeWire-Pulse configuration rather than a kernel driver.

## macOS privacy permissions

macOS system-output capture uses Core Audio process taps and requires macOS 14.2+ plus the applicable system-audio recording privacy permission. Hosted CI can validate the HAL virtual cable but cannot pre-grant or prove a real user's TCC choices.

## Remote inference/providers

When raw audio, text, or voice-profile material is sent off-device:

- require explicit selection/configuration of that remote execution mode;
- use encrypted transport (TLS) for non-local endpoints;
- authenticate remote services/providers;
- make retention policies explicit where a provider/service controls retention;
- never assume a remote worker can dereference local filesystem voice-profile paths;
- do not leak API keys through exception text, logs or list APIs;
- keep communication-platform routing independent from provider selection.

See [`remote-workers.md`](remote-workers.md).

## Local API/browser boundary

- local runtime services bind to loopback by default;
- Expo web/PWA origins are restricted through the runtime CORS origin policy;
- the resource WebSocket uses the same origin policy;
- the optional browser extension is an integration surface, not a privileged shortcut around runtime APIs;
- browser/UI code must not gain arbitrary local-file/model-worker access;
- the retired HTML Studio/fetch monkey-patches/iframe-eval compatibility paths must not return.

## Logs and diagnostics

Normal diagnostics may include:

- model IDs;
- runtime/profile/backend IDs;
- process IDs and ephemeral localhost endpoints;
- audio endpoint IDs/names;
- queue/counter/latency data;
- health and error classes.

They should not automatically include:

- conversation audio;
- saved voice references;
- raw API credentials/tokens;
- private signing material;
- full conversation transcripts/translations unless an explicit diagnostic workflow requires and clearly discloses them.

## Trust and code execution

Model/catalog metadata is not permission to execute arbitrary code.

- repository-shipped drivers/adapters should be reviewed code;
- `trust_remote_code=True` or equivalent third-party code execution should remain clearly surfaced and deliberate;
- unverified catalog entries must not silently replace active/validated models;
- model installation and runtime-profile provisioning are explicit actions;
- backend runtime definitions describe reusable trusted deployment families rather than arbitrary model-supplied shell commands;
- production driver signing credentials must never be committed to the repository.
