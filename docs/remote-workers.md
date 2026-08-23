# Remote inference workers

VoxPassport can route ASR, translation, and TTS independently to a worker you
operate on Google Colab, AWS, a private VPS, or another trusted machine. This
makes mixed operation possible: for example, local VAD and TTS with cloud ASR
and translation. VAD deliberately stays local because it is in the audio
capture loop and must respond within a few milliseconds.

## Configure a worker

In **Model Settings → Active Engines**, select **DEPLOY CLOUD** for the model
you want to move off-device (or choose **Cloud Configuration** from its
three-dot menu). Add the worker's HTTPS base URL and an optional token
environment-variable name, such as `VOXPASSPORT_AWS_TOKEN`. The token value is
never written to `data/remote_endpoints.json` or returned by the API.

Each capability becomes a normal active model choice. Activating a cloud
translation model does not move ASR or TTS; those can stay local or be routed
to another cloud worker. The application checks `GET /health` before changing
the active pipeline, preserving the current model when the worker is down.

## Worker HTTP contract (v1)

All requests include `Authorization: Bearer <token>` when configured.

| Capability | Request | Response |
| --- | --- | --- |
| Health | `GET /health` | Any 2xx/3xx confirms readiness |
| Translation | `POST /v1/translation` with `text`, `source_language`, `target_language`, and optional `context` | JSON `{ "translated_text": "…", "latency_ms": 0 }` |
| ASR | `POST /v1/asr/transcribe` with base64 PCM S16LE, sample rate, channels, and language | JSON `{ "text": "…" }` |
| TTS | `POST /v1/audio/speech` with `input`, `language`, `voice_profile_id`, `is_cloned`, `stream: true`, and `response_format: "pcm"` | Raw PCM S16LE response body, with optional `x-sample-rate` header |

Remote ASR is utterance-streamed: local VAD detects the end of a phrase and
sends that phrase to the worker. Translation and TTS remain pipeline stages,
so captions and synthesized audio automatically flow back through the local
audio buses. Use HTTPS for every non-local worker; the UI rejects plaintext
remote URLs.

For cloned remote TTS, the worker must have access to the referenced voice
profile ID via your own secure profile synchronization. Until that is set up,
use stock voice mode for remote TTS.
