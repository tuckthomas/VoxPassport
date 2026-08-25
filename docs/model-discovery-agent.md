# VoxPassport Model Discovery Agent

## Purpose

`ModelDiscoveryAgent` watches the fast-changing model ecosystem and surfaces credible candidates without destabilizing a working installation.

Discovery is research/recommendation, not automatic architectural integration. A discovered model must not justify a model-specific application adapter, UI exception, command environment, fixed port, or supervisor branch merely because it is new.

## Candidate filters

Before recommending a model, evaluate:

- required capability and target-language coverage;
- licensing and redistribution/commercial constraints;
- package/download size;
- measured or credible runtime memory requirements;
- latency and actual streaming behavior;
- dependency/runtime compatibility;
- official/community/remote-code trust level;
- whether it maps to an existing adapter/driver/backend runtime/runtime profile;
- whether an official downloadable repository is known and verified enough to expose a normal install action.

English/Romanian remains the primary benchmark pair, but discovery is not architecturally limited to that pair.

## Discovery versus installability

A catalog entry can be useful for research even when it is not currently installable.

The backend/model-manager API owns the user-facing action state:

```json
{
  "installable": false,
  "installation_reason": "No verified official downloadable repository is configured for this catalog entry."
}
```

The Expo client renders this metadata. It must not reconstruct discovery trust/installability rules from model names or `upstream_id` itself.

## TTS integration classification

Classify every local TTS candidate in this order.

### 1. Existing driver + existing backend/runtime profiles

Best case: add a schema-v3 model manifest and benchmark it.

For a proxy-backed model, reference an existing reusable `backend_runtime` and supply the model-specific `backend_args`, typically a checkpoint.

No new launch command or environment variable is permitted merely because the checkpoint/model ID changed.

### 2. Existing driver + new backend server family

Use this when the inference protocol fits an existing reusable driver but the backend server implementation/lifecycle is genuinely new.

Add one backend runtime definition under `runtime/tts_backend_runtimes/`. The family owns dependency profile, launch contract, arguments, health endpoint and remote override policy.

Future models on that family should then be manifest-only.

### 3. New driver + existing runtime/backend family

Use only when inference semantics cannot be represented by an existing `TtsDriver`.

The new implementation belongs behind the generic worker driver boundary, never in Expo or the main application adapter layer.

### 4. New dependency family

Add/reuse a runtime profile only when Python/PyTorch/CUDA/native-library constraints genuinely conflict with existing environments.

A runtime profile is dependency topology, not a new application architecture.

### 5. Explicit remote deployment

A backend runtime may point to an explicitly configured non-loopback remote service. Unmanaged localhost GPU backends are invalid because they would escape supervisor residency ownership.

## Non-TTS candidates

For ASR, translation, VAD, diarization and direct-speech candidates, distinguish:

1. **discoverable/research-worthy**;
2. **download/installable**;
3. **implemented by a production runtime adapter**;
4. **locally benchmarked/validated**;
5. **safe to recommend as an active replacement**.

These are not equivalent states. A downloadable model with no implemented runtime adapter must not be presented as ready for activation.

Direct speech providers use the provider catalog/adapter/session contract rather than being forced into the modular ASR/NMT/TTS slot architecture.

## Integration rule

```text
new model on supported backend family
    -> model manifest only

new dependency family
    -> runtime profile

new backend server implementation
    -> reusable backend runtime definition

new protocol/model-library semantics
    -> reusable driver/adapter

new application UI/provider-name routing
    -> almost never
```

Proposals such as `NewFooTtsAdapter` in the application layer, `VOXPASSPORT_FOO_MODEL_TTS_COMMAND`, or a fixed localhost port dedicated to one checkpoint should be treated as architectural regressions unless they represent a genuinely reusable primitive.

## Recommendation states

| State | Description |
| --- | --- |
| `IGNORE` | Not relevant or fails filters |
| `WATCH` | Interesting but not ready for benchmarking |
| `CANDIDATE` | Passes initial filters |
| `RECOMMENDED_FOR_LOCAL_BENCHMARK` | Evidence is strong enough for controlled local evaluation |
| `RECOMMENDED_UPGRADE` | Wins the required local acceptance criteria |

Do not assign `RECOMMENDED_UPGRADE` solely from vendor benchmarks or marketing claims.

## Metadata to record

For model candidates, record the relevant subset of:

- capability;
- source/target languages;
- voice cloning/cross-lingual cloning support;
- reference-transcript requirement;
- actual streaming support;
- compatible application adapter or TTS driver;
- compatible reusable backend runtime, if any;
- required dependency/runtime profiles;
- checkpoint/model arguments;
- package size;
- measured runtime RAM/VRAM;
- first-result/first-audio latency and RTF where applicable;
- license/trust/remote-code constraints;
- official downloadable repository/revision;
- local benchmark evidence.

## User control

The discovery agent may recommend research/benchmark/install actions, but must not silently:

- download multi-GB models unless explicitly configured to do so;
- activate a newly discovered model;
- create/install a dependency profile without an explicit installation action;
- add a backend runtime when an existing reusable family fits;
- rewrite application routing for one model;
- promote a model without the required validation;
- transmit local audio or voice-profile material to a remote candidate merely because it was discovered.

## Active-session stability

Discovery must not destabilize a live translation session. New candidates can be recorded while a session is active, but model/strategy/routing mutation remains subject to the normal runtime transaction/active-session restrictions.
