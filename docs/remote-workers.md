# Remote Inference Workers

VoxPassport can route ASR, translation, and TTS independently to a trusted off-device worker while keeping the product UI and native desktop audio local. This allows mixed operation—for example, local VAD and native capture with remote ASR/translation and local TTS.

VAD remains local because it sits in the capture/endpointing loop and benefits from deterministic low latency.

## Remote workers are not local TTS workers

These are separate execution boundaries:

```text
Local TTS worker/backend
  purpose: local dependency/model/process isolation
  ownership: VoxPassport TTS supervisor
  transport: ephemeral loopback HTTP
  architecture: ManifestTtsAdapter -> voxpassport.tts.v1 -> TtsDriver

Remote inference worker
  purpose: off-device execution on infrastructure you operate
  ownership: explicitly configured remote endpoint
  transport: HTTPS + configured authentication
  architecture: Remote*Adapter -> remote worker contract
```

The isolated Coqui/XTTS environment under `runtime/profiles/coqui-xtts/.venv` is therefore still local execution, not a remote deployment.

## Product/client boundary

The canonical Expo client configures remote/self-hosted runtime targets and model choices through typed APIs. It does not communicate directly with GPU worker processes or carry raw realtime PCM through React state.

For desktop conferencing, capture and output routing remain local and platform-native even when inference is remote:

```text
Physical/system audio
       ↓
local native helper
       ↓
local runtime
       ↓
remote ASR / translation / TTS as configured
       ↓
local runtime/native output
       ↓
VoxPassport Virtual Microphone or Local Monitor
```

Changing inference location does not change Meet/Zoom/Teams routing.

## Configure a remote worker

A remote endpoint is represented through the runtime's remote-endpoint/model APIs and appears as a capability-specific model choice. Configure:

- human-readable endpoint name;
- HTTPS base URL;
- supported capabilities;
- optional authentication token environment-variable name;
- optional selected remote model identity.

Secret token values should remain outside API list responses and should not be persisted in plaintext client configuration.

Each capability can be routed independently. Activating a remote translation model does not automatically move ASR or TTS.

The runtime checks endpoint health before committing activation so a failed remote candidate does not unnecessarily replace a working active model.

## Remote worker HTTP contract

When configured, requests use:

```text
Authorization: Bearer <token>
```

| Capability | Request | Response |
| --- | --- | --- |
| Health | `GET /health` | accepted readiness response |
| Translation | `POST /v1/translation` with text/source/target/context | JSON translated text + latency metadata |
| ASR | `POST /v1/asr/transcribe` with encoded PCM, rate, channels and language | JSON transcript |
| TTS | `POST /v1/audio/speech` with the remote TTS request fields | audio response with sample-rate metadata |

Remote ASR remains utterance-oriented in the modular pipeline: local VAD/endpointing determines committed speech boundaries before the phrase is sent to the worker. Returned captions and synthesized audio continue through the same local runtime/native routing contracts.

Use TLS for non-loopback workers. Plain localhost HTTP is reserved for VoxPassport-owned local services/processes bound to loopback.

## Remote cloned TTS

A remote TTS worker cannot automatically dereference:

```text
data/voice_profiles/<profile>/reference.wav
```

on the user's computer.

Remote voice cloning therefore needs an explicit design such as:

- secure user-approved profile synchronization;
- explicit remote enrollment/upload;
- provider-managed voice identity with its own consent/persistence policy;
- stock remote voice with no local profile transfer.

Do not silently upload a saved local voice profile merely because a remote TTS model is activated.

## Direct speech providers are a different strategy

Provider-neutral direct speech translation is separate from the modular remote-worker capability slots. A direct provider implements the translation-strategy/session contract and may receive streaming audio according to its configured execution mode.

The client and conference routing remain provider-neutral; Google/Gemini-specific wire behavior stays behind the provider adapter.

## Runtime topology independence

Persistent model/endpoint identity and ephemeral process topology are separate concerns:

```text
Model registry / runtime state
  -> active remote model and endpoint identity

Local TTS supervisor
  -> ephemeral local worker/backend PIDs and ports

Native desktop routing
  -> stable local audio endpoint IDs

Expo client
  -> low-frequency configuration/session state
```

A local worker restart or dynamic port change does not change model identity. Likewise, moving one capability to a remote worker does not require a different UI architecture or virtual-microphone implementation.

## Managed cloud is deferred

The current architecture supports local/self-hosted endpoints and leaves room for a future managed allocation/control plane. Automatic worker allocation, short-lived media credentials, usage accounting and hosted pricing remain deferred product scope; they are not required for the current local desktop workflow.
