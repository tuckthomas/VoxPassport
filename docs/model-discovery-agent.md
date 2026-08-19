# Model Discovery Agent — LiveTranslator

## Purpose

The `ModelResearchAgent` runs on a weekly schedule (configurable) to watch the rapidly-changing open-model ecosystem and surface credible improvements without destabilizing the working installation.

## Schedule

- **Default:** Once per week
- Configurable: disable, run manually, or change schedule
- Never runs during an active conference session
- GPU-intensive local benchmarking is deferred while a call is active

## Discovery Sources

Primary sources only:
- Official model repositories (Hugging Face, GitHub)
- Official model cards
- Official research papers
- Recognized benchmark leaderboards with transparent methodology
- Upstream GitHub releases and tags

**Never relies on:** Social media claims, marketing copy, unverified third-party benchmark tables.

## Candidate Identification

Searches for newly released or materially updated models in:
- Streaming ASR
- Multilingual ASR
- Machine translation / streaming MT
- Text-to-Speech / multilingual TTS
- Zero-shot voice cloning
- Direct speech-to-speech translation
- VAD/endpointing

**Filters applied before recommendation:**
- Must have English and Romanian language capability
- Must have a usable license for the intended deployment
- Must not exceed configured hardware limits (unless labeled "Requires hardware upgrade")

## Recommendation States

| State | Description |
|-------|-------------|
| `IGNORE` | Not relevant or fails filters |
| `WATCH` | Interesting but not ready for benchmarking |
| `CANDIDATE` | Passes filters; eligible for local benchmark |
| `RECOMMENDED_FOR_LOCAL_BENCHMARK` | Strong published evidence; user prompted to download |
| `RECOMMENDED_UPGRADE` | Passes local benchmark; better than current active model |

**Note:** `RECOMMENDED_UPGRADE` is never set solely from vendor-published benchmarks.

## Promotion Policy (Default Conservative)

A candidate is recommended for activation only if:
- No material Romanian quality regression
- No unacceptable p95 latency regression
- No license regression
- No unsupported runtime dependency
- At least one material improvement in accuracy, latency, voice quality, VRAM, or storage

## User Control

For every credible candidate, the agent notifies the user with:
- Which active model it may replace
- Why it may be better (evidence-based)
- Published benchmark data
- Model size and hardware requirements
- License information
- "Download & Benchmark" button

**The agent never:**
- Automatically downloads multi-GB models (unless user enables this)
- Automatically activates a newly discovered model
- Promotes a model without local verification first
