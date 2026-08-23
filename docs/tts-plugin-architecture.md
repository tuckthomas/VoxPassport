# TTS Plugin Architecture

VoxPassport worker-backed TTS models use a three-layer integration model:

1. **Adapters normalize transport/protocol.** The main inference daemon talks to one `ManifestTtsAdapter` and the stable `voxpassport.tts.v1` HTTP protocol.
2. **Drivers normalize model libraries/backends.** A worker-side `TtsDriver` contains the smallest amount of code required to adapt a model library or backend to streaming PCM, load/unload, capabilities, and metrics.
3. **Manifests describe models.** JSON manifests declare model identity, aliases, languages, cloning support, worker endpoint, audio format, driver entrypoint/options, and registry metadata.

The main daemon must not gain another model-name `if` branch when a compatible TTS model is added.

## Directory layout

```text
runtime/
  inference/
    adapters/tts/
      manifest_tts_adapter.py     # one main-process adapter
    tts_plugins/
      manifest.py                 # schema + catalog + alias resolution
      registry_bridge.py          # manifest -> existing model registry
  tts_manifests/
    xtts-v2-romanian-v2.json
    moss-tts-1.5.json
    voxcpm-2.json
  workers/
    tts_host/
      server.py                   # stable voxpassport.tts.v1 host
      protocol.py                 # TtsDriver contract
      driver_loader.py
      drivers/
        xtts_romanian.py          # XTTS-specific library behavior
        openai_proxy.py           # reusable OpenAI-style backend driver
```

Concrete `MossTtsAdapter`, `VoxCpmTtsAdapter`, and `XttsRomanianTtsAdapter` class names remain only as compatibility shims. They subclass `ManifestTtsAdapter`; new runtime code should use manifests rather than those names.

## Stable worker protocol

The generic host binds to `127.0.0.1:8098` by default and exposes:

```text
GET  /health
GET  /v1/capabilities?model_id=<id>
POST /load
POST /unload
POST /v1/audio/speech
GET  /metrics
```

`POST /load` accepts:

```json
{
  "model_id": "xtts-v2-romanian-v2"
}
```

Streaming synthesis uses a model-independent request:

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

Only fields relevant to a voice profile are included. The response is mono signed 16-bit little-endian PCM with sample-rate/layout headers. `response_format: "wav"` is used for preview/export requests.

## Adding a model that fits an existing driver

When a new model already exposes an OpenAI-style local `/v1/audio/speech` service, **do not write another VoxPassport adapter**. Add a manifest using:

```json
"driver": {
  "entrypoint": "runtime.workers.tts_host.drivers.openai_proxy:OpenAiSpeechProxyDriver",
  "options": {
    "backend_url": "http://127.0.0.1:PORT",
    "health_path": "/v1/models",
    "speech_path": "/v1/audio/speech"
  }
}
```

The manifest options can also describe:

- static backend payload fields such as model/voice;
- whether language is sent as a code, full language name, or omitted;
- reference-audio field name and data-URI/path encoding;
- reference-transcript field name;
- backend URL environment-variable override;
- timeout and streaming field names.

MOSS-TTS v1.5 and VoxCPM2 use this same driver despite having different payload conventions and language support.

After adding the JSON manifest and restarting VoxPassport, the daemon registers it and the Model Settings UI discovers it from registry metadata. No new daemon routing branch or JavaScript model insertion is required.

## Adding a model with genuinely different inference semantics

If a model cannot be expressed with an existing driver, add a small `TtsDriver` implementation rather than another application adapter.

A driver implements:

```python
class TtsDriver:
    def load(self) -> None: ...
    def unload(self) -> None: ...
    def synthesize_pcm(self, request) -> Iterator[bytes]: ...
    def capabilities(self) -> dict: ...
    def metrics(self) -> dict: ...
    def health_check(self) -> bool: ...
```

`TtsDriver.synthesize_wav()` has a default implementation that wraps PCM into a WAV, so a driver normally needs only streaming PCM unless its backend already produces a better native WAV response.

XTTS Romanian is the proof case for a genuinely model-specific driver. Its driver owns the XTTS/Coqui behavior while the main process still sees the same generic worker protocol.

## Capability negotiation

Manifest capability metadata is the startup/discovery fallback. Once a driver is loaded, `/load` and `/v1/capabilities` return runtime capabilities and `ManifestTtsAdapter` treats those as authoritative for:

- languages;
- streaming support;
- voice-cloning support;
- cross-lingual cloning;
- transcript requirements;
- native sample rate and sample format.

This prevents application code from assuming that a worker loaded exactly the features its catalog entry advertised.

## Voice profiles

Voice profiles remain model-independent:

```text
data/voice_profiles/<profile>/reference.wav
                              reference.txt
                              conditioning/ro.wav   # optional derived target conditioning
```

`ManifestTtsAdapter` resolves the canonical profile once and sends normalized reference fields through `voxpassport.tts.v1`. Drivers decide how those fields map to the underlying model/backend.

The XTTS manifest declares `conditioning/{language}.wav`, so the same generic adapter can supply the optional Romanian GPT-conditioning bridge without XTTS-specific application code.

## Hot swap and GPU safety

The TTS host owns one active driver at a time. Loading another manifest unloads the prior driver before activating the replacement. The host holds its runtime lock for a committed utterance, so a hot swap waits until that utterance finishes.

The main `ManifestTtsAdapter` still enters VoxPassport's heavyweight GPU coordinator while a local TTS request is running. A separate worker process therefore does not bypass the shared 8 GB GPU scheduling policy.

## Native exceptions

Some engines are not worker-backed yet. OmniVoice and the native Higgs/audiocpp path remain explicit in-process/native exceptions. They can be migrated later by placing their library/DLL behavior behind a `TtsDriver`; this refactor does not force that migration before their existing paths are stable.

## Validation

`tests/test_tts_plugin_architecture.py` verifies that:

- XTTS, MOSS, and VoxCPM resolve through `ManifestTtsAdapter`;
- MOSS and VoxCPM share one proxy driver;
- model aliases come from manifests;
- malformed manifests fail clearly;
- a synthetic new TTS manifest can route without adding daemon model-name branches;
- the generic controller performs load, streaming PCM, WAV wrapping, capabilities, metrics, and unload with a fake driver.

These tests run in Runtime Integrity CI without downloading TTS weights.
