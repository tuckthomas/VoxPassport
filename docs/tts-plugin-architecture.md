# TTS Plugin, Backend-Runtime, and Runtime-Profile Architecture

All local VoxPassport TTS models use one application architecture. There are no model-specific application adapters, fixed model worker/backend ports, unmanaged localhost GPU backends, or native/in-process exceptions.

The boundary is split into five concerns:

1. **`ManifestTtsAdapter`** — the single application-side TTS adapter and `voxpassport.tts.v1` client.
2. **TTS model manifests** — model identity, capabilities, driver settings, worker `runtime_profile`, and optional `backend_runtime` + model-specific `backend_args`.
3. **Backend runtime definitions** — reusable server-family lifecycle metadata: dependency profile, launch template/family override, health endpoint, remote override policy, and accepted arguments.
4. **`TtsRuntimeSupervisor`** — process topology, dynamic endpoints, health, residency, hot swap, rollback, crash recovery, and idle shutdown.
5. **`TtsDriver` implementations** — normalize model libraries, DLLs, or backend protocols behind the common worker protocol.

The main daemon and orchestrator must not gain model-name branches when another local TTS model is added.

## Current topology

```text
TTS model manifest
       │
       ├── model identity / capabilities
       ├── driver entrypoint + model-specific options
       ├── runtime_profile
       ├── backend_runtime (optional)
       └── backend_args (optional)
                │
                ▼
        TtsRuntimeSupervisor
                │
      ┌─────────┴────────────────────┐
      ▼                              ▼
 generic worker profile       BackendRuntimeCatalog
 ephemeral worker port              │
      │                              ├── backend profile
      │                              ├── reusable launch template
      │                              ├── argument contract
      │                              ├── health policy
      │                              └── remote override policy
      │                                      │
      ▼                                      ▼
   TtsDriver ◄──────────────── managed backend process
      │                              ephemeral port
      ▼
 model / DLL / explicit remote backend
```

A **model manifest** answers what the model is and which reusable pieces it needs. A **backend runtime** answers how one server family is launched and supervised. A **runtime profile** answers which dependency-compatible Python/toolchain environment executes a worker or backend. The **supervisor** decides where and when the processes run.

Ephemeral endpoints are operational state and are never persisted as model identity.

## Directory layout

```text
runtime/
  inference/
    adapters/tts/
      manifest_tts_adapter.py
      profile_reference.py
    tts_plugins/
      backend_runtime.py
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
      uv.lock                # generated/verified in connected dev environment
      .venv/                 # ignored
  tts_backend_runtimes/
    higgs-openai-server.json
    moss-openai-server.json
    voxcpm-openai-server.json
  tts_manifests/
    omnivoice-stock.json
    higgs-tts-3.json
    higgs-tts-3-q4_k_m.json
    moss-tts-1.5.json
    voxcpm-2.json
    xtts-v2-romanian-v2.json
  workers/tts_host/
    server.py
    protocol.py
    driver_loader.py
    drivers/
      omnivoice.py
      higgs_native.py
      openai_proxy.py
      xtts_romanian.py
      xtts_runtime.py
      xtts_common.py
```

## TTS model manifest schema

Local TTS model manifests use schema version 3. They must not own process topology.

A direct-worker model can be as simple as:

```json
{
  "schema_version": 3,
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

A model served by an existing backend family references that reusable backend runtime:

```json
{
  "schema_version": 3,
  "model_id": "moss-tts-1.5",
  "runtime_profile": "core",
  "backend_runtime": "moss-openai-server",
  "backend_args": {
    "checkpoint": "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"
  },
  "driver": {
    "entrypoint": "runtime.workers.tts_host.drivers.openai_proxy:OpenAiSpeechProxyDriver",
    "options": {
      "speech_path": "/v1/audio/speech"
    }
  }
}
```

Model manifests reject legacy `worker`, `driver.options.backend_process`, `driver.options.backend_url`, and `driver.options.backend_url_env` topology.

## Reusable backend runtimes

Backend runtime definitions live under `runtime/tts_backend_runtimes/` and use schema version 1.

Example family definition:

```json
{
  "schema_version": 1,
  "backend_runtime_id": "moss-openai-server",
  "runtime_profile": "core",
  "launch": {
    "command_env": "VOXPASSPORT_TTS_BACKEND_MOSS_COMMAND"
  },
  "remote_url_env": "VOXPASSPORT_TTS_BACKEND_MOSS_URL",
  "health_path": "/v1/models",
  "startup_timeout_seconds": 120,
  "endpoint_driver_option": "backend_url",
  "arguments": {
    "checkpoint": {
      "required": true
    }
  }
}
```

The command environment is **backend-family configuration**, not model integration. Configure it once for a server implementation. Any number of model manifests can then reuse that backend runtime and supply only `backend_args` such as another checkpoint.

Backend runtime command arrays support these built-in placeholders:

- `{host}`
- `{port}`
- `{project_root}`
- `{model_id}`
- `{backend_runtime_id}`
- `{python}`

They also support every declared `backend_args` key, such as `{checkpoint}`.

A backend runtime can provide a static reusable command directly instead of `command_env` when the repository has a canonical launch command. Family-level environment overrides exist for deployments where the upstream server command is installation-specific.

A `remote_url_env` may point only to an explicit **non-loopback remote service**. A loopback override is rejected because localhost GPU processes must remain supervisor-owned.

## What “hot-swappable” means

The intended integration rule is:

```text
New model on an already-supported backend family
    -> model manifest only

New dependency family
    -> runtime profile

New backend server implementation
    -> one reusable backend runtime definition

New backend/model protocol semantics
    -> one reusable TtsDriver if an existing driver cannot express them

New application adapter / daemon branch / supervisor model-name branch
    -> almost never
```

For example, adding another MOSS checkpoint does **not** require another `VOXPASSPORT_<MODEL>_TTS_COMMAND`. It references `moss-openai-server` and supplies a different `backend_args.checkpoint`.

## Runtime profiles

Runtime profiles represent dependency-compatible families, not individual models.

| Profile | Environment | Intended models |
| --- | --- | --- |
| `core` | primary `.venv` | compatible direct drivers and current proxy/backend families |
| `coqui-xtts` | `runtime/profiles/coqui-xtts/.venv` | XTTS/Coqui |

A backend runtime can select a runtime profile independently from the generic worker model manifest. This allows a future backend server to use an incompatible Python/toolchain environment without forcing its proxy driver or another TTS model into that same environment.

Do not create one environment per model by default.

## Why XTTS is isolated

The main VoxPassport environment can follow a different Transformers/PyTorch lifecycle from Coqui XTTS. Keeping `coqui-xtts` isolated prevents unrelated ASR/TTS dependency changes from pinning or breaking each other. The isolation is a dependency boundary, not a special application architecture.

## Supervisor responsibilities

`TtsRuntimeSupervisor` owns the local TTS lifecycle:

- resolve the model manifest and worker runtime profile;
- validate/resolve an optional backend runtime and its model arguments;
- resolve the backend runtime's own dependency profile when applicable;
- start the generic worker only when needed;
- bind worker/backend processes to dynamic `127.0.0.1` ports;
- build backend launch commands from the reusable runtime template plus `backend_args`;
- health-check workers and managed backends;
- inject only the ephemeral endpoint into the worker driver at load time;
- keep one active supervised local TTS model by default on constrained hardware;
- reuse a worker for same-profile model switches while unloading the old driver;
- terminate the previous managed backend before replacement activation;
- terminate incompatible previous-profile workers before cross-profile activation;
- roll back to the previous model/backend when replacement activation fails;
- recycle a backend whose PID is alive but health endpoint is not;
- retry a worker once if it dies before first audio;
- never replay automatically after partial audio was emitted;
- terminate idle and process-exit children safely.

The supervisor remains model-agnostic. Its source must not contain XTTS/Higgs/MOSS/OmniVoice/VoxCPM routing branches.

## Worker boundary

The generic worker deliberately **does not load the backend-runtime catalog**. Backend runtime metadata is deployment state owned by the supervisor. The supervisor validates it before launch and passes only runtime driver overrides—normally a dynamically assigned backend URL—to the worker.

Every supervised worker exposes:

```text
GET  /health
GET  /v1/capabilities?model_id=<id>
POST /load
POST /unload
POST /v1/audio/speech
GET  /metrics
```

`POST /load` accepts a supervisor-only `driver_options_override` object for ephemeral deployment data. It is never persisted back into the manifest.

## Runtime profile provisioning

Use:

```bat
.venv\Scripts\python.exe scripts\manage_runtime_profile.py status coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py install coqui-xtts
.venv\Scripts\python.exe scripts\manage_runtime_profile.py repair coqui-xtts
```

`coqui-xtts` is an independent uv project. Incompatible runtime families should remain independent projects rather than one shared uv workspace.

## GPU residency and recovery

A local proxy backend is part of its model's supervised residency. On switch VoxPassport unloads the prior driver, terminates its managed backend process tree, terminates an incompatible worker profile if required, then starts and health-checks the replacement before committing active state.

Explicit non-loopback remote backends execute elsewhere and therefore are not local GPU residency.

## Voice profiles

Voice profiles remain model-independent:

```text
data/voice_profiles/<profile>/reference.wav
                              reference.txt       # optional unless selected model requires it
                              conditioning/ro.wav # optional derived target conditioning
```

Transcript requirements come from the selected manifest. Driver-specific conditioning must not replace `reference.wav`.

## Diagnostics

`/api/resources` reports:

- active worker runtime profile/model;
- worker process, PID, dynamic endpoint, health, and loaded model;
- managed backend model ID;
- **backend runtime ID and backend runtime profile**;
- backend PID, dynamic endpoint, health path/state, and unexpected exit.

The canonical Expo Runtime/Diagnostics surface marks the active TTS runtime broken when either supervised layer fails.

## Validation

Runtime Integrity verifies:

- schema-v3 model manifests contain no model-owned process topology;
- reusable backend-runtime definitions validate independently;
- proxy model manifests reference backend runtime IDs;
- two different synthetic model manifests can use one backend runtime with different checkpoint arguments;
- required and unknown backend args fail validation before synthesis;
- dynamic worker/backend ports remain supervisor-owned;
- same-profile worker reuse and cross-profile eviction;
- managed backend termination and unhealthy-backend recycling;
- rollback and pre-audio crash recovery;
- no model-name dispatch returns to the supervisor/daemon;
- the old concrete application adapters and fixed-host architecture remain removed.
