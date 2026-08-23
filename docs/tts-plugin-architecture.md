# TTS Plugin and Runtime-Profile Architecture

All local VoxPassport TTS models use one application architecture. There are no model-specific application adapters, fixed model worker/backend ports, unmanaged localhost GPU backends, or native/in-process exceptions.

The boundary is intentionally split into four concerns:

1. **`ManifestTtsAdapter`** normalizes the application-side TTS contract and `voxpassport.tts.v1` transport.
2. **TTS manifests** describe the model, capabilities, driver, logical `runtime_profile`, and any declarative local-backend launch contract it requires.
3. **`TtsRuntimeSupervisor`** owns local process topology: interpreter selection, worker/backend startup, dynamic localhost endpoints, health checks, model residency, crash recovery, and idle shutdown.
4. **`TtsDriver` implementations** normalize model libraries, DLLs, or backend protocols behind the common worker protocol.

The main daemon and orchestrator must not gain model-name branches when another local TTS model is added.

## Current topology

```text
TTS model manifest
       │
       ├── model identity / capabilities
       ├── driver entrypoint + options
       ├── runtime_profile
       └── optional backend_process contract
                │
                ▼
        TtsRuntimeSupervisor
                │
      ┌─────────┴───────────────┐
      ▼                         ▼
 runtime-profile worker   managed proxy backend
 ephemeral port           ephemeral port, if needed
      │                         │
      ▼                         │
   TtsDriver ───────────────────┘
      │
      ▼
 model / DLL / explicit remote backend
```

A model manifest answers **what runtime family and backend lifecycle does this driver require?** The supervisor answers **where are those local processes currently running?** Ephemeral endpoints are operational state and are never persisted as model identity.

## Directory layout

```text
runtime/
  inference/
    adapters/tts/
      manifest_tts_adapter.py
      profile_reference.py
    tts_plugins/
      manifest.py
      registry_bridge.py
      runtime_profiles.py
      runtime_supervisor.py
      runtime_status.py
      runtime_cleanup.py
  profiles/
    runtime_profiles.json
    coqui-xtts/
      pyproject.toml
      uv.lock                # generated/updated by uv sync in a connected dev environment
      .venv/                 # ignored
  tts_manifests/
    omnivoice-stock.json
    higgs-tts-3.json
    higgs-tts-3-q4_k_m.json
    moss-tts-1.5.json
    voxcpm-2.json
    xtts-v2-romanian-v2.json
  workers/
    tts_host/
      server.py
      protocol.py
      driver_loader.py
      requirements-xtts.txt  # fallback when uv is unavailable
      drivers/
        omnivoice.py
        higgs_native.py
        openai_proxy.py
        xtts_romanian.py
        xtts_runtime.py
        xtts_common.py
```

## Manifest schema

Local TTS manifests use schema version 2. A manifest contains a logical runtime profile and must **not** contain a VoxPassport worker URL or fixed worker port.

Example:

```json
{
  "schema_version": 2,
  "model_id": "xtts-v2-romanian-v2",
  "runtime_profile": "coqui-xtts",
  "driver": {
    "entrypoint": "runtime.workers.tts_host.drivers.xtts_romanian:XttsRomanianDriver",
    "options": {}
  },
  "capabilities": {
    "languages": ["en", "ro"],
    "streaming": true,
    "voice_cloning": true,
    "cross_lingual_voice_cloning": true
  },
  "audio": {
    "sample_rate_hz": 24000,
    "sample_format": "pcm_s16le"
  }
}
```

`TtsManifest` rejects a legacy `worker` section. This prevents deployment topology from leaking back into model metadata.

### Proxy backend declarations

A proxy driver that needs a **local** server declares a launch contract rather than a localhost URL:

```json
{
  "driver": {
    "entrypoint": "runtime.workers.tts_host.drivers.openai_proxy:OpenAiSpeechProxyDriver",
    "options": {
      "backend_url_env": "VOXPASSPORT_EXAMPLE_TTS_URL",
      "backend_process": {
        "command_env": "VOXPASSPORT_EXAMPLE_TTS_COMMAND",
        "startup_timeout_seconds": 120
      },
      "health_path": "/v1/models",
      "speech_path": "/v1/audio/speech"
    }
  }
}
```

The local command is resolved by the supervisor, which allocates `{host}` and `{port}` dynamically. Command arrays may also use `{project_root}`, `{model_id}`, and `{python}` placeholders. The resulting endpoint is injected into the worker only for that runtime instance.

An explicit `backend_url_env` may point to a **non-loopback remote endpoint**. That is allowed because the remote service cannot occupy the local GPU. An unmanaged `localhost`/`127.0.0.1` proxy URL is rejected: a local proxy backend must be supervisor-owned.

Full Higgs, MOSS, and VoxCPM use this contract. Their manifests no longer contain fixed `8095`/`8096`/`8097` addresses.

## Runtime profiles

Runtime profiles represent **dependency-compatible families**, not individual models.

Current profiles:

| Profile | Environment | Intended models |
| --- | --- | --- |
| `core` | primary `.venv` | OmniVoice, native Higgs, proxy drivers, and other TTS drivers compatible with the primary stack |
| `coqui-xtts` | `runtime/profiles/coqui-xtts/.venv` | XTTS/Coqui |

A new model should reuse an existing profile whenever its dependency graph is compatible. Create a new profile only when there is a genuine conflict or isolation requirement, such as a different Python version, incompatible Transformers/PyTorch constraints, native-library requirements, or deliberate fault isolation.

Do **not** create one environment per model by default.

## Why XTTS is isolated

The main VoxPassport environment currently follows Hugging Face Transformers from Git because the ASR stack can require unreleased support. Coqui XTTS constrains Transformers to the range it supports. Combining those dependency graphs would let an unrelated ASR upgrade break XTTS or force the rest of VoxPassport to remain pinned to XTTS-compatible dependencies.

The separate runtime profile is therefore intentional. What was removed is the old special-case topology where XTTS implicitly meant a dedicated fixed port.

## Runtime supervisor responsibilities

`TtsRuntimeSupervisor` owns the complete local TTS process lifecycle:

- resolve `manifest.runtime_profile`;
- find the configured interpreter for that profile;
- start the generic worker host only when the model is actually needed;
- bind the worker to an available `127.0.0.1` port selected at runtime;
- use the supervisor's actual manifest catalog when starting workers;
- start a declared local proxy backend on its own dynamic localhost port;
- wait for worker and managed-backend health;
- inject dynamic backend endpoints as runtime-only driver options;
- request `/load` for the target model and validate post-load health;
- maintain one active local TTS model across runtime profiles on constrained hardware;
- reuse one worker when switching between models in the same compatible profile;
- unload the previous driver and terminate its managed backend before activating the replacement;
- terminate complete managed backend process trees rather than only the top-level launcher;
- roll back to the previous manifest/backend when replacement activation fails;
- restart crashed workers/backends and retry once when failure occurs before any audio has been emitted;
- unload released models and shut idle workers down after the profile's timeout;
- terminate owned worker/backend processes during process exit as a final cleanup safeguard.

The supervisor is model-agnostic. Its source must not contain names such as XTTS, Higgs, MOSS, OmniVoice, or VoxCPM.

## True on-demand startup

`ManifestTtsAdapter.load()` is deliberately cheap. It marks the application adapter ready but does not spawn a TTS process.

The physical runtime is started by the supervisor only when:

- an explicit TTS activation performs a health check; or
- synthesis actually begins.

Therefore a `CAPTIONS_ONLY` session can start the normal inference pipeline without launching any TTS worker or managed proxy backend.

## Stable worker protocol

Every supervised host exposes the same local protocol:

```text
GET  /health
GET  /v1/capabilities?model_id=<id>
POST /load
POST /unload
POST /v1/audio/speech
GET  /metrics
```

`POST /load` also accepts a supervisor-only `driver_options_override` object. It exists for ephemeral deployment data such as a dynamically assigned managed-backend URL. Those options are retained for the loaded driver but are never written back to the manifest.

A synthesis request remains model-independent:

```json
{
  "model": "xtts-v2-romanian-v2",
  "input": "Bună ziua.",
  "language": "ro",
  "response_format": "pcm",
  "ref_audio_path": "C:/.../reference.wav",
  "ref_text": "optional transcript",
  "target_conditioning_path": "C:/.../conditioning/ro.wav"
}
```

Only fields relevant to the selected profile/model are included. Streaming responses are mono signed 16-bit little-endian PCM with sample-rate/layout headers. WAV output is used for preview/export flows.

## Adding a new TTS model

### If an existing driver already fits

Add a manifest, choose an existing runtime profile, and configure the driver. No application adapter, daemon branch, fixed port, or JavaScript model-routing case should be added.

For an OpenAI-style **local** TTS service, reuse the proxy driver and declare how the supervisor starts it:

```json
"driver": {
  "entrypoint": "runtime.workers.tts_host.drivers.openai_proxy:OpenAiSpeechProxyDriver",
  "options": {
    "backend_url_env": "VOXPASSPORT_EXAMPLE_TTS_URL",
    "backend_process": {
      "command_env": "VOXPASSPORT_EXAMPLE_TTS_COMMAND"
    },
    "health_path": "/v1/models",
    "speech_path": "/v1/audio/speech"
  }
}
```

If `VOXPASSPORT_EXAMPLE_TTS_URL` is set to a non-loopback endpoint, the explicit remote service is used. Otherwise `VOXPASSPORT_EXAMPLE_TTS_COMMAND` must supply the local launch command, preferably as a JSON string array. A loopback URL without a supervisor launch contract is invalid.

### If inference semantics are genuinely different

Add a small worker-side `TtsDriver`:

```python
class TtsDriver:
    def load(self) -> None: ...
    def unload(self) -> None: ...
    def synthesize_pcm(self, request) -> Iterator[bytes]: ...
    def capabilities(self) -> dict: ...
    def metrics(self) -> dict: ...
    def health_check(self) -> bool: ...
```

The main application still sees only `ManifestTtsAdapter`.

### If dependencies are incompatible

Add a runtime profile rather than a model-specific worker architecture. The profile declares its interpreter/provisioning metadata; the manifest references the profile by ID. A backend launch command can point at another compatible interpreter/toolchain when the backend itself has distinct requirements.

## Runtime profile provisioning

Use the generic management command:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

`coqui-xtts` is an independent uv project at `runtime/profiles/coqui-xtts/pyproject.toml`. When `uv` is available, the provisioner runs `uv sync` for that project, producing its own `.venv` and `uv.lock`. It is intentionally **not** a member of a shared uv workspace because incompatible runtime families need independent dependency resolution.

When uv is unavailable, the same profile metadata contains declarative fallback pip installation steps. `runtime/workers/tts_host/requirements-xtts.txt` exists only for that fallback.

The initial `uv.lock` must be generated/verified in an environment with package-index access. It should then be committed for reproducible installs.

## GPU residency and hot swap

The supervisor enforces one active supervised local TTS model across profiles. A local proxy backend is part of that model's residency, not an exception.

On a switch, VoxPassport:

1. drains/unloads the selected worker-side driver;
2. terminates the prior model's managed backend process tree, if any;
3. terminates an incompatible runtime-profile worker when required;
4. starts the replacement backend/worker and health-checks them;
5. commits the new active model only after successful load.

This avoids simultaneous local TTS residency on an 8 GB-class GPU. Explicit non-loopback remote backends are outside local GPU residency because they execute elsewhere.

`ManifestTtsAdapter` still enters VoxPassport's heavyweight GPU coordinator around each actual local synthesis request, so ASR and local TTS do not intentionally launch heavyweight GPU work concurrently.

Same-profile model changes reuse the existing worker process but unload the previous driver before loading the next one.

A committed synthesis request remains protected by the worker's runtime lock, so a same-host model switch waits for the utterance boundary.

## Crash recovery semantics

A worker or managed backend that dies while active is detected before reuse and recreated.

If the worker disconnects **before any output audio has been emitted**, the generic adapter asks the supervisor to recreate the model's supervised processes and retries the utterance once. If audio was already emitted, VoxPassport does not replay the sentence automatically because doing so could duplicate audible speech.

Activation failure is transactional: the supervisor attempts to restore the previously active TTS manifest, including relaunching its managed backend when necessary, rather than leaving the local TTS slot in a half-switched state.

## Voice profiles

Voice profiles remain model-independent:

```text
data/voice_profiles/<profile>/reference.wav
                              reference.txt       # optional unless selected model requires it
                              conditioning/ro.wav # optional derived target conditioning
```

Transcript requirements come from the selected manifest. Driver-specific conditioning is derived from these canonical assets and must not replace `reference.wav`.

## Diagnostics

`/api/resources` includes a `tts_runtime` section with:

- active runtime profile;
- active local TTS model;
- per-profile installation/running state, PID, endpoint, loaded model, idle timeout, and worker health;
- managed proxy backend model ID, PID, dynamic endpoint, health path, health result, unexpected-exit state, and exit code.

Model Settings marks the runtime **broken** if either the active generic worker or its managed proxy backend exits/becomes unreachable.

Ephemeral endpoints are diagnostic state only; they are not stored in model manifests or registry identity.

Worker stdout/stderr is written under `data/logs/tts-worker-<profile>.log`. Managed backend output is written under `data/logs/tts-backend-<model-id>.log`.

## Validation

Runtime Integrity covers both architecture invariants and real subprocess lifecycle behavior. Tests verify:

- schema-v2 manifests contain `runtime_profile` and no worker topology;
- all local TTS models use the single application adapter;
- runtime profiles group dependency-compatible models;
- worker and managed-backend ports are supervisor-owned and dynamic;
- logical adapter load does not spawn unused TTS processes;
- models in one profile reuse one worker process;
- cross-profile switching terminates the incompatible previous worker;
- managed proxy backends are started, health-checked, endpoint-injected, and terminated on switch/release;
- unmanaged loopback proxy backends are rejected;
- released workers stop after their idle timeout;
- worker death during activation rolls back the previous model;
- worker death before first audio is restarted and retried;
- the supervisor contains no model-specific dispatch logic;
- the old fixed-host launcher and XTTS-specific installer remain removed.
