# VoxPassport Model Discovery Agent

## Purpose

`ModelResearchAgent` watches the fast-changing open-model ecosystem and surfaces credible improvements without destabilizing a working installation.

Discovery is research/recommendation, not automatic architectural integration. A newly discovered TTS model must not justify a model-specific application adapter, command environment, fixed port, or daemon/supervisor branch.

## Candidate filters

Before recommending a model, evaluate:

- target-language coverage;
- licensing;
- package and runtime memory requirements;
- latency and real streaming support;
- dependency compatibility;
- official/community/remote-code trust level;
- whether it fits an existing driver, backend runtime, and runtime profile.

English/Romanian remains the primary benchmark pair, but the model system is not limited to that pair.

## TTS integration classification

Classify every local TTS candidate in this order.

### 1. Existing driver + existing backend/runtime profiles

Best case. Add a schema-v3 model manifest and benchmark it.

For a proxy-backed model this means referencing an existing reusable `backend_runtime` and supplying model-specific `backend_args`, usually a checkpoint.

No new launch command or environment variable is permitted merely because the checkpoint/model ID changed.

### 2. Existing driver + new backend server family

Use when inference HTTP semantics already fit a driver such as `OpenAiSpeechProxyDriver`, but the server implementation/lifecycle is genuinely new.

Add one reusable backend runtime definition under `runtime/tts_backend_runtimes/`. That family definition may specify its dependency profile, launch template/family override, argument contract, health endpoint, and remote override policy.

Future models on that server family should then be manifest-only.

### 3. New driver + existing runtime/backend family

Use only when the model's inference semantics cannot be expressed by an existing driver.

The new code belongs behind the generic worker `TtsDriver` boundary, never in the main application adapter layer.

### 4. New dependency family

Add/reuse a runtime profile only when Python/PyTorch/CUDA/Transformers/native-library constraints genuinely conflict with existing environments.

A runtime profile is dependency topology, not a new application architecture.

### 5. Explicit remote deployment

A backend runtime may use a non-loopback remote URL override. The local application still consumes the same model manifest and generic driver contract. Unmanaged localhost GPU backends are invalid.

## Integration rule

```text
new model on supported backend family
    -> model manifest only

new dependency family
    -> runtime profile

new backend server implementation
    -> one reusable backend runtime definition

new protocol/model-library semantics
    -> reusable TtsDriver

new application adapter / model-name supervisor routing
    -> almost never
```

The discovery agent should treat any proposal such as `NewFooTtsAdapter`, `VOXPASSPORT_FOO_MODEL_TTS_COMMAND`, or `localhost:81xx for Foo` as an architectural regression unless the proposal is actually a new reusable backend/runtime primitive rather than one model's integration.

## Recommendation states

| State | Description |
| --- | --- |
| `IGNORE` | Not relevant or fails filters |
| `WATCH` | Interesting but not ready for benchmarking |
| `CANDIDATE` | Passes initial filters |
| `RECOMMENDED_FOR_LOCAL_BENCHMARK` | Strong enough evidence for local evaluation |
| `RECOMMENDED_UPGRADE` | Wins required local acceptance criteria |

Do not assign `RECOMMENDED_UPGRADE` solely from vendor benchmarks.

## TTS metadata to record

For a TTS candidate record:

- target languages;
- voice cloning and cross-lingual cloning support;
- whether a reference transcript is required;
- real streaming behavior;
- compatible `TtsDriver`;
- compatible reusable backend runtime, if any;
- required worker/backend dependency profiles;
- checkpoint/model arguments;
- package size and measured runtime memory;
- first-audio latency and RTF;
- licensing and distribution constraints.

## User control

The discovery agent may recommend benchmark/install work, but must not silently:

- download multi-GB models unless configured to do so;
- activate a newly discovered model;
- create a dependency profile without an installation action;
- add a backend runtime when an existing family already fits;
- rewrite TTS application routing for one model;
- promote a model without local verification.
