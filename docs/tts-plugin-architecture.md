# TTS Plugin Architecture

All local VoxPassport TTS models use one architecture. There are no model-specific application adapters and no native/in-process exceptions.

1. **`ManifestTtsAdapter` normalizes transport/protocol.** The main inference daemon talks to the stable `voxpassport.tts.v1` HTTP protocol.
2. **`TtsDriver` implementations normalize model libraries/backends.** Driver code contains the smallest amount of model-specific behavior required to produce streaming PCM, load/unload resources, expose capabilities, and report metrics.
3. **JSON manifests describe models.** Manifests declare identity, aliases, languages, cloning support, worker endpoint, audio format, driver entrypoint/options, and registry metadata.

The main daemon and orchestrator must not gain model-name branches when another local TTS model is added.

## Directory layout

```text
runtime/
  inference/
    adapters/tts/
      manifest_tts_adapter.py     # the only local TTS application adapter
      profile_reference.py        # model-independent voice-profile resolution
    tts_plugins/
      manifest.py                 # schema + catalog + alias resolution
      registry_bridge.py          # manifest -> model registry
  tts_manifests/
    omnivoice-stock.json
    higgs-tts-3.json
    higgs-tts-3-q4_k_m.json
    moss-tts-1.5.json
    voxcpm-2.json
    xtts-v2-romanian-v2.json
  workers/
    tts_host/
      server.py                   # stable voxpassport.tts.v1 host
      protocol.py                 # TtsDriver contract
      driver_loader.py
      drivers/
        omnivoice.py              # OmniVoice library behavior
        higgs_native.py           # audiocpp/native Higgs behavior
        openai_proxy.py           # reusable HTTP backend driver
        xtts_romanian.py          # XTTS driver entrypoint
        xtts_runtime.py           # XTTS/Coqui implementation details
```

The old `OmniVoiceTtsAdapter`, `HiggsTtsAdapter`, `HiggsNativeTtsAdapter`, `MossTtsAdapter`, `VoxCpmTtsAdapter`, and `XttsRomanianTtsAdapter` files have been removed. The temporary XTTS/plugin daemon subclasses and the XTTS-specific HTTP worker server have also been removed.

## Stable worker protocol

A generic host exposes:

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

Only fields relevant to the selected voice/profile are included. The response is mono signed 16-bit little-endian PCM with sample-rate/layout headers. `response_format: "wav"` is used for preview/export requests.

## Worker environments are not separate architectures

The protocol boundary allows different Python dependency environments without adding different application paths.

`run.bat` starts:

```text
primary .venv     -> generic TTS host :8098
isolated XTTS env -> generic TTS host :8099 (when installed)
main daemon       -> runtime/inference/server/main.py
```

The primary host can load OmniVoice, native Higgs, full Higgs proxy, MOSS, VoxCPM, and other compatible manifests. XTTS uses the same host implementation and protocol on port 8099 because Coqui's dependency stack is intentionally isolated from Parakeet/Transformers.

Dependency isolation therefore does not create another TTS architecture.

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

The reusable proxy driver supports declarative options for:

- static request payload fields such as model/voice;
- per-stream or per-WAV payload fields;
- language as a code, full language name, or omitted;
- flat cloned-reference fields or a references array;
- reference-audio field names and data-URI/path encoding;
- reference-transcript field names;
- backend URL environment-variable overrides;
- optional backend unload endpoints;
- timeout and stream-field names.

MOSS-TTS v1.5, VoxCPM2, and full Higgs TTS use this same driver despite different request conventions.

After adding a JSON manifest and restarting VoxPassport, the daemon registers it and Model Settings discovers it from registry metadata. No daemon routing branch or JavaScript model insertion is required.

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

`TtsDriver.synthesize_wav()` has a default PCM-to-WAV implementation, so a driver normally needs only streaming PCM unless its backend already produces a better native WAV response.

Examples of genuinely distinct drivers are:

- `OmniVoiceDriver` for the local OmniVoice Python library;
- `HiggsNativeDriver` for the `audiocpp_engine.dll` Q4 path;
- `XttsRomanianDriver` for XTTS/Coqui and its Romanian conditioning behavior.

Those differences remain worker-side implementation details. The main process still sees only `ManifestTtsAdapter`.

## Capability negotiation

Manifest capability metadata is the startup/discovery fallback. Once a driver is loaded, `/load` and `/v1/capabilities` return runtime capabilities and `ManifestTtsAdapter` treats those as authoritative for:

- languages;
- streaming support;
- voice-cloning support;
- cross-lingual cloning;
- transcript requirements;
- native sample rate and sample format.

Studio/manual synthesis also uses the manifest's transcript requirement. It no longer applies the old rule that every non-OmniVoice engine requires a transcript.

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

Each generic TTS host owns one active driver at a time. Loading another manifest on that host unloads its prior driver before activating the replacement. The host holds its runtime lock for a committed utterance, so a hot swap waits until that utterance finishes.

The orchestrator also unloads the previous `ManifestTtsAdapter` when the active TTS model changes. This is important across dependency hosts: switching away from XTTS on `:8099` explicitly unloads the XTTS driver before a primary-host model uses the shared GPU.

The main `ManifestTtsAdapter` enters VoxPassport's heavyweight GPU coordinator while a local TTS request is running, so worker processes do not bypass the shared-GPU scheduling policy.

## Registry ownership

TTS metadata and aliases live only in `runtime/tts_manifests` and are bridged into the registry at startup. The general built-in model catalog does not contain TTS entries, and `ModelManagerController` does not hard-code local TTS aliases or native-Higgs registration behavior.

## Validation

`tests/test_tts_plugin_architecture.py` and `tests/integration/test_tts_adapter_integrity.py` enforce that:

- every local TTS model is represented by a manifest;
- every local TTS model uses `ManifestTtsAdapter` in the application process;
- the old concrete adapter/server files remain deleted;
- the main daemon and orchestrator contain no model-specific local TTS dispatch tree;
- full Higgs, MOSS, and VoxCPM share the reusable proxy driver;
- OmniVoice, native Higgs, and XTTS driver modules can be discovered without eagerly importing heavyweight model libraries;
- a synthetic new TTS manifest routes without a daemon model-name branch;
- the generic controller performs load, streaming PCM, WAV output, cloned-reference propagation, capabilities, metrics, and unload with a fake driver.

These tests run in Runtime Integrity CI without downloading TTS weights.
