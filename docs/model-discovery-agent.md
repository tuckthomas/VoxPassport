# VoxPassport Model Discovery Agent

## Purpose

`ModelResearchAgent` periodically watches the fast-changing open-model ecosystem and surfaces credible improvements without destabilizing a working installation.

Discovery is **research and recommendation**, not automatic architectural integration. A newly discovered TTS model does not justify adding a model-specific application adapter or daemon branch.

## Schedule

- Default: periodic/weekly research cadence when enabled.
- Can be disabled or run manually.
- Must not disrupt an active conference session.
- GPU-intensive local benchmarking is deferred while live use has priority.

## Discovery sources

Prefer primary or authoritative sources:

- official model repositories;
- official model cards;
- official GitHub releases/tags;
- research papers;
- benchmark leaderboards with disclosed methodology;
- upstream runtime/library documentation.

Community reports can be useful for identifying candidates or operational problems, but should not by themselves justify promotion.

## Candidate identification

Search areas include:

- streaming/multilingual ASR;
- machine translation;
- text-to-speech and voice cloning;
- direct speech translation;
- diarization;
- VAD/endpointing.

Filters before recommendation should include:

- required target-language coverage;
- usable licensing for the intended deployment;
- download and runtime memory requirements;
- latency/streaming suitability;
- dependency/runtime compatibility;
- whether required code is official, community, or remote-code execution;
- whether the model can fit an existing integration boundary.

English/Romanian remains the primary project benchmark pair, but the model system itself is not limited to that pair.

## TTS candidate integration classification

For every local TTS candidate, classify integration cost before recommending implementation:

### 1. Existing driver + existing runtime profile

Best case. Add a manifest and benchmark the model. No new application adapter or daemon routing is permitted.

### 2. New driver + existing runtime profile

Use when the model library has genuinely different inference semantics but its dependencies are compatible with an existing local worker environment.

### 3. Existing/new driver + new runtime profile

Use when dependency constraints, Python version, native libraries, or fault isolation make the model unsafe to install into existing environments.

The new environment should still run the same generic TTS host and `voxpassport.tts.v1` protocol. A runtime profile is dependency topology, not a new application architecture.

### 4. Separate upstream backend / remote deployment

Use the appropriate proxy or remote-worker contract when the model is naturally served by an external process or machine.

The discovery agent should never recommend `New FooTtsAdapter` as the normal local-TTS integration strategy. Local TTS application code should continue to see only `ManifestTtsAdapter`.

## Recommendation states

| State | Description |
| --- | --- |
| `IGNORE` | Not relevant or fails filters |
| `WATCH` | Interesting but not ready for benchmarking |
| `CANDIDATE` | Passes initial filters |
| `RECOMMENDED_FOR_LOCAL_BENCHMARK` | Strong enough evidence to justify local evaluation |
| `RECOMMENDED_UPGRADE` | Wins the required local benchmark/acceptance criteria |

`RECOMMENDED_UPGRADE` should not be set solely from vendor-published benchmarks.

## Promotion policy

A candidate should be recommended for activation only if it does not introduce an unacceptable regression in the dimensions relevant to its capability, including:

- target-language quality;
- p95/first-output latency;
- streaming stability;
- licensing;
- dependency/runtime compatibility;
- VRAM/RAM pressure;
- storage;
- voice identity/naturalness for cloning-capable TTS.

At least one material benefit should justify the swap.

For TTS, also record whether the candidate:

- requires a reference transcript;
- supports cross-lingual voice cloning;
- can use existing model-independent voice profiles;
- needs a separate runtime profile;
- requires a native DLL or separate backend;
- supports real streaming PCM rather than post-hoc chunking.

## User control

For every credible candidate, surface:

- which active capability/model it could replace;
- why it may be better;
- published evidence;
- package/weight size;
- estimated and observed runtime memory where available;
- dependency/runtime-profile requirements;
- license information;
- benchmark/install action.

The agent should not silently:

- download multi-GB models unless explicitly configured to do so;
- activate a newly discovered model;
- create a new runtime profile without an explicit installation action;
- rewrite the TTS architecture to accommodate one model;
- promote a model without local verification.
