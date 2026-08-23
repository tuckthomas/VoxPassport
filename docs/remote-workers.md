# Remote Inference Workers

VoxPassport can route ASR, translation, and TTS independently to a worker you operate on Google Colab, AWS, a private VPS, or another trusted machine. This makes mixed operation possible: for example, local VAD and TTS with remote ASR and translation. VAD deliberately stays local because it is in the audio capture loop and must respond quickly.

## Remote workers are not local TTS plugin hosts

VoxPassport also uses local worker processes for manifest-driven TTS model isolation. Those localhost workers implement the internal `voxpassport.tts.v1` protocol and run worker-side `TtsDriver` implementations.

Do not conflate the two concepts:

```text
Local TTS worker
  purpose: local model-library / dependency / process isolation
  trust: localhost process owned by VoxPassport
  architecture: ManifestTtsAdapter -> voxpassport.tts.v1 -> TtsDriver

Remote inference worker
  purpose: off-device execution on infrastructure you operate
  trust: explicit configured remote endpoint
  transport: HTTPS + configured authentication
  architecture: Remote*Adapter -> remote worker contract
```

The current XTTS `.venv-xtts` process is a **local TTS worker**, not a remote inference deployment.

## Configure a remote worker

In **Model Settings → Active Engines**, select **DEPLOY CLOUD** for the model you want to move off-device or choose **Cloud Configuration** from its menu. Add the worker's HTTPS base URL and an optional token environment-variable name such as `VOXPASSPORT_AWS_TOKEN`.

The token value should never be persisted in plain configuration returned by the API.

Each capability becomes a normal active-model choice. Activating a remote translation model does not move ASR or TTS; those can remain local or be routed independently. The application checks `GET /health` before changing the active pipeline so the current model can remain selected when the remote worker is unavailable.

## Remote worker HTTP contract

All requests include `Authorization: Bearer <token>` when configured.

| Capability | Request | Response |
| --- | --- | --- |
| Health | `GET /health` | Any accepted readiness response |
| Translation | `POST /v1/translation` with `text`, `source_language`, `target_language`, and optional `context` | JSON `{ "translated_text": "…", "latency_ms": 0 }` |
| ASR | `POST /v1/asr/transcribe` with encoded PCM, sample rate, channels, and language | JSON `{ "text": "…" }` |
| TTS | `POST /v1/audio/speech` with the remote-worker TTS request fields | Raw PCM response with sample-rate metadata |

Remote ASR is utterance-streamed: local VAD determines phrase boundaries and sends the committed phrase to the worker. Translation and TTS remain pipeline stages so captions and synthesized audio flow back through the same local audio buses.

Use HTTPS for every non-local worker. Plaintext localhost HTTP is acceptable for VoxPassport-owned local services because they bind to loopback; that exception does not apply to remote deployments.

## Remote cloned TTS

A remote TTS worker cannot automatically dereference a local `data/voice_profiles/<id>` path. It therefore needs one of the following designs:

- secure profile synchronization managed by the user;
- an explicit enrollment/upload flow for the remote worker;
- a remote stock voice that requires no local profile material.

Until secure profile synchronization exists, stock-voice remote TTS is the simpler configuration.

## Runtime topology independence

The model registry should store the active remote model/endpoint identity, while local TTS runtime profiles and local worker ports remain a separate concern. The planned local TTS runtime supervisor does not replace remote-worker configuration; it only centralizes lifecycle management for VoxPassport-owned local TTS processes.
