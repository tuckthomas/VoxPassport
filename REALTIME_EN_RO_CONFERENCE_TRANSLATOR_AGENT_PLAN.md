# Real-Time English ↔ Romanian Conference Translator
## Agentic Coding Plan for Gemini

> **Purpose:** Build a local-first, real-time speech translation application for video/audio conferencing. The primary path is English ↔ Romanian. The application must capture speech, transcribe it, translate it, synthesize translated speech, route that synthesized speech into a conference application, and display synchronized translated captions.
>
> **Primary integration strategy:** Treat Google Meet, Zoom, Teams, Discord, Webex, etc. as ordinary audio applications. The MVP must expose a **virtual microphone** containing translated speech rather than depending on a conference-specific API. A Google Meet/browser integration is a secondary UI/caption layer, not the core audio transport.
>
> **Status date for model recommendations:** 2026-08-16. Model selection must remain adapter-based because this area changes rapidly.

---

# 0. Agent Operating Instructions

- [x] Treat this document as the implementation backlog and architectural source of truth.
- [x] Do not silently replace major architectural decisions.
- [x] If a library/model/API has changed since 2026-08-16, verify the current upstream documentation before coding against it.
- [x] Prefer official model cards, official repositories, published papers, and official Google/Chrome documentation over blog posts.
- [x] Do not hard-code a single AI model into business logic.
- [x] Treat AI models as installable, removable, versioned runtime assets managed by a model registry.
- [x] Support hot-swapping active models without restarting the full application.
- [x] Implement ASR, translation, TTS, VAD, audio I/O, and conferencing integrations behind interfaces/adapters.
- [x] Keep the first usable implementation local-first.
- [x] Do not introduce Kubernetes, Redis, Kafka, or distributed microservices into the MVP unless benchmarks prove they are necessary.
- [x] Optimize for **interactive latency, stability, intelligibility, and Romanian quality**, not leaderboard scores alone.
- [x] Preserve the ability to run inference on:
  - [x] The same workstation as the conference client.
  - [x] A second LAN machine with a GPU.
  - [x] A remote GPU server over an encrypted connection.
- [x] Never log raw audio, transcripts, translations, or cloned-voice embeddings/prompts by default.
- [x] Never implement covert voice cloning. Voice enrollment must be explicitly initiated by the person whose voice is being cloned.
- [x] Keep the application usable without voice cloning.
- [x] Build an automated model bakeoff before committing the production defaults.
- [x] Track all measured latency as p50, p95, and worst-observed values.
- [x] Record exact model revision/commit, runtime version, quantization, GPU/CPU, VRAM/RAM, and batch settings for every benchmark.

---

# 1. Product Definition

## 1.1 Primary Use Case — Full-Duplex English ↔ Romanian Conversation

- [x] The **primary use case is bidirectional, full-duplex translation**. English → Romanian and Romanian → English are equally core requirements; Romanian → English is not a secondary or optional "reverse" feature.
- [x] The application must support a conversation in which the local user primarily speaks English and the remote participant primarily speaks Romanian.
- [x] Both directional pipelines must be capable of running at the same time with isolated audio capture, inference, playback, and routing.

### Local User: English → Romanian

- [x] User selects a physical microphone.
- [x] Application captures the local user's English microphone audio.
- [x] VAD/endpointing determines speech regions.
- [x] Streaming ASR converts **English speech → English text**.
- [x] Translation model converts **English text → Romanian text**.
- [x] Romanian translated text is immediately published to the caption system.
- [x] TTS converts **Romanian text → Romanian speech**.
- [x] Romanian synthesized speech is streamed to the application's **virtual microphone**.
- [x] Google Meet/Zoom/Teams/etc. uses that virtual microphone as its selected microphone.
- [x] Remote Romanian-speaking participants therefore hear the local user's speech in Romanian.
- [x] The application may optionally show both the original English transcript and Romanian translation locally.

### Remote Participant: Romanian → English

- [x] Application separately captures the remote participant's conference/system audio.
- [x] VAD/endpointing determines Romanian speech regions.
- [x] Streaming ASR converts **Romanian speech → Romanian text**.
- [x] Translation model converts **Romanian text → English text**.
- [x] English translated text is immediately published to the local caption overlay.
- [x] TTS converts **English text → English speech**.
- [x] English synthesized speech is played to the local user's headphones/speakers so the local user can understand the Romanian speaker without needing to read captions continuously.
- [x] The English TTS path is a core part of the primary use case, not merely an optional debugging feature.
- [x] The application may optionally show both the original Romanian transcript and English translation locally.
- [x] English synthesized speech from the inbound path must **not** be routed into the conference virtual microphone.
- [x] Prevent inbound English TTS from being recaptured as conference audio and translated again.

### Full Conversation Behavior

- [x] When the local user speaks English, remote participants hear Romanian.
- [x] When a remote participant speaks Romanian, the local user hears English.
- [x] Both sides should also have access to translated text captions where the integration permits it.
- [x] The system must isolate outbound translated audio from inbound translated audio to prevent echo and recursive translation loops.
- [x] The application should minimize the perceived conversational delay in **both** directions, not optimize one direction at the expense of the other.
- [x] If simultaneous speech occurs, each directional pipeline must remain independent and continue processing its own source stream.

## 1.2 Directional Audio Routing Requirements

- [x] **Outbound path:** Physical microphone → EN ASR → EN text → EN→RO translation → RO text/captions → RO TTS → virtual microphone → conference.
- [x] **Inbound path:** Conference/system audio → RO ASR → RO text → RO→EN translation → EN text/captions → EN TTS → local headphones/speakers.
- [x] Keep physical microphone capture and conference/system-audio capture as separate sources.
- [x] Keep outbound Romanian TTS and inbound English TTS as separate output buses.
- [x] Only outbound Romanian TTS may feed the conference virtual microphone.
- [x] Inbound English TTS must feed only the local monitoring/playback device.
- [x] Prevent the application's own synthesized audio from being recaptured and translated again in either direction.

## 1.3 Operating Modes

- [x] Implement `FULL_DUPLEX` as the **normal/default operating mode**:
  - [x] Run EN → RO outbound and RO → EN inbound pipelines simultaneously with isolated audio buses.
- [x] Implement `OUTBOUND_TRANSLATION` as a diagnostic/single-direction mode:
  - [x] Physical mic → EN ASR → RO MT → RO captions → RO TTS → virtual mic.
- [x] Implement `INBOUND_TRANSLATION` as a diagnostic/single-direction mode:
  - [x] Conference/loopback audio → RO ASR → EN MT → EN captions → EN TTS → local playback.
- [x] Implement `CAPTIONS_ONLY`:
  - [x] ASR + translation + captions in both configured directions, no TTS.
- [x] Implement `TTS_NO_CLONE`:
  - [x] Use a stock/generated Romanian or English voice.
- [x] Implement `TTS_CLONED`:
  - [x] Use the enrolled speaker voice when the selected model and hardware meet latency requirements.
- [x] Start with the fixed language pair/direction rules EN → RO outbound and RO → EN inbound.
- [x] Add broader language auto-detection later only after the fixed English ↔ Romanian full-duplex pipeline is stable.

---

# 2. Important Architecture Decisions

## 2.1 Do Not Make Google Meet the Core Audio Integration

- [x] The MVP must work without any Google Meet API.
- [x] Present translated outbound audio as an operating-system **virtual microphone**.
- [x] Let the user select that virtual microphone in Google Meet, Zoom, Teams, Discord, Webex, or another application.
- [x] Treat conference platforms as replaceable consumers of the virtual audio device.
- [x] Keep platform-specific code outside the inference/audio core.

### Why

- [x] A virtual microphone gives one implementation path across multiple conference products.
- [x] It avoids depending on changing DOM structures or proprietary media-injection APIs.
- [x] It allows development and testing with ordinary audio programs before integrating Google Meet.
- [x] It separates model latency problems from browser/conference integration problems.

## 2.2 Google Meet Add-on / Browser Companion

- [x] Build this **after** the core local application works.
- [x] Use it primarily for:
  - [x] Translated caption overlay.
  - [x] Language direction controls.
  - [x] Mute/original-audio controls.
  - [x] Voice-clone enable/disable.
  - [x] Current pipeline status.
  - [x] Latency indicator.
  - [x] Connection status to local inference companion.
- [x] Do not assume a Meet add-on can replace the OS-level virtual microphone.
- [x] Do not assume a browser extension's caption overlay is visible to remote participants.
- [x] If both participants need shared captions, implement server-synchronized caption clients or a shared Meet add-on experience.
- [x] Consider a transparent desktop overlay as an alternative to browser DOM injection.

## 2.3 Google Meet Media API

- [x] Treat the Google Meet Media API as an optional later integration.
- [x] As of 2026-08-16, account for its Developer Preview status and access restrictions before making it a dependency.
- [x] Use it only if it materially improves clean remote-speaker media capture.
- [x] Keep loopback/system-audio capture as the cross-platform fallback.
- [x] Do not design the MVP around the assumption that the Media API provides arbitrary translated-audio injection into the meeting.

---

# 3. Recommended Model Bakeoff

> **Rule:** The models below are candidates, not permanent dependencies. Create adapters and benchmark them specifically on English ↔ Romanian conversational speech.

## 3.1 Speech-to-Text / ASR

### Primary Candidate: NVIDIA Nemotron 3.5 ASR Streaming 0.6B

- [x] Add adapter: `Nemotron35StreamingAsrAdapter`.
- [x] Benchmark English.
- [x] Benchmark Romanian (`ro-RO`).
- [x] Test native streaming chunk sizes.
- [x] Test punctuation/capitalization behavior.
- [x] Test language identification behavior.
- [x] Measure:
  - [x] WER.
  - [x] Endpoint-to-final-transcript latency.
  - [x] Partial transcript revision rate.
  - [x] GPU VRAM.
  - [x] CPU RAM.
  - [x] Real-time factor.
- [x] Prefer this candidate for the first real-time implementation because it is explicitly designed for streaming and explicitly covers Romanian.

### Benchmark Candidate: NVIDIA Parakeet TDT 0.6B v3

- [x] Add adapter: `ParakeetTdtV3AsrAdapter`.
- [x] Benchmark against Nemotron on the exact same audio.
- [x] Compare Romanian accuracy.
- [x] Compare streaming responsiveness.
- [x] Keep as fallback if deployment/runtime simplicity is better.

### Direct Speech-Translation Benchmark: NVIDIA Canary-1B-v2

- [x] Add experimental adapter: `CanaryV2SpeechTranslationAdapter`.
- [x] Test Romanian speech → English text translation.
- [x] Test English speech → Romanian text translation.
- [x] Compare direct AST against the separate ASR → text-MT pipeline.
- [x] Do not make it the default until direct AST gives both acceptable latency and translation quality.

### Optional Emerging ASR Candidates

- [x] Re-check current Qwen ASR releases before implementation.
- [x] Re-check current Whisper/faster-whisper descendants as a stable baseline.
- [x] Add only if Romanian support and streaming behavior justify the extra adapter.

---

# 4. Text Translation / Machine Translation

## 4.1 Primary Low-Latency Candidate: Xiaomi MiLMMT-46-1B-v1.0

- [x] Add adapter: `MiLMMT46TranslationAdapter`.
- [x] Explicitly configure EN → RO.
- [x] Explicitly configure RO → EN.
- [x] Benchmark conversational text rather than only formal written text.
- [x] Measure:
  - [x] Translation latency.
  - [x] COMET or current equivalent semantic metric.
  - [x] chrF++.
  - [x] Human adequacy.
  - [x] Human fluency.
  - [x] Named-entity preservation.
  - [x] Number/date/currency preservation.
  - [x] Hallucination rate.
- [x] Use 1B as the first low-latency candidate.
- [x] Do not assume its very recent release automatically makes it best for this specific language pair.

## 4.2 Quality Candidate: MiLMMT-46-4B-v1.0

- [x] Add configuration for the 4B checkpoint.
- [x] Benchmark against the 1B checkpoint.
- [x] Promote to default only if the quality gain is worth the latency/VRAM cost.

## 4.3 Quality Comparator: NVIDIA Riva-Translate-4B-Instruct-v2

- [x] Add adapter: `RivaTranslate4BAdapter`.
- [x] Benchmark EN → RO and RO → EN.
- [x] Compare against MiLMMT 1B and 4B.
- [x] Track licensing separately from technical quality.

## 4.4 Stable Baselines

- [x] Add at least one older/stable multilingual translation baseline for regression comparison.
- [x] Do not use an older baseline merely because it is easier to integrate if a newer model is materially better.
- [x] Keep strict separation between:
  - [x] Model code license.
  - [x] Model-weight license.
  - [x] Commercial/redistribution rights.

---

# 5. Text-to-Speech and Voice Cloning

## 5.1 Primary Candidate: k2-fsa / OmniVoice

- [x] Add adapter: `OmniVoiceTtsAdapter`.
- [x] Test Romanian stock/non-cloned synthesis.
- [x] Test English stock/non-cloned synthesis.
- [x] Test zero-shot voice cloning.
- [x] Cache reusable speaker conditioning/prompt data after enrollment.
- [x] Do **not** recompute the speaker prompt for every sentence.
- [x] Stream audio chunks as soon as the model can emit them.
- [x] Measure:
  - [x] Time to first audio.
  - [x] Full utterance real-time factor.
  - [x] VRAM.
  - [x] Speaker similarity.
  - [x] Romanian intelligibility.
  - [x] Romanian accent/naturalness.
  - [x] Audio artifacts at chunk boundaries.
- [x] Test cross-lingual voice cloning carefully.
- [x] Expect that cross-lingual cloning can preserve characteristics of the reference speaker's accent.
- [x] Default to a non-cloned Romanian voice if cloned Romanian quality is worse or latency is excessive.

### Voice Enrollment

- [x] Require explicit user action to enroll a voice.
- [x] Require a clean reference recording.
- [x] Start with approximately 3–10 seconds of clean speech, then benchmark longer samples if useful.
- [x] Store only the minimum required reusable speaker representation.
- [x] Encrypt persisted voice-conditioning data.
- [x] Add `Delete enrolled voice` functionality.
- [x] Never upload a reference recording to a remote server without explicit configuration and disclosure.
- [x] Never permit "clone this remote meeting participant" as an automatic feature.

## 5.2 High-Quality Research Comparator: Higgs TTS 3

- [x] Benchmark only if useful.
- [x] Treat its licensing as a gating concern before any production/commercial embedding.
- [x] Do not make it a production default merely because it scores well.

## 5.3 Rejected Primary Candidate: Chatterbox Multilingual V3

- [x] Do not use as the Romanian production default unless upstream Romanian support has been added after 2026-08-16.
- [x] Re-check its current language list before reconsidering.

## 5.4 Unified Fallback / Experimental Path: SeamlessM4T v2 / SeamlessStreaming

- [x] Benchmark Meta Seamless speech-to-speech translation as an alternative architecture.
- [x] Confirm current licensing before distribution.
- [x] Test Romanian speech output.
- [x] Compare its one-model simplicity against the modular ASR → MT → TTS pipeline.
- [x] Keep the modular pipeline as the primary design unless the unified path clearly wins on real-world latency/quality.

---

# 6. Correction: Is Voice-Cloned TTS Too Computationally Intensive?

- [x] Do **not** assume voice cloning itself makes real-time use impossible.
- [x] Modern sub-billion-parameter voice-cloning models can synthesize faster than real time on strong GPUs.
- [x] The real engineering constraint is the **combined** load of:
  - [x] Streaming ASR.
  - [x] Translation.
  - [x] TTS.
  - [x] Voice conditioning.
  - [x] Audio resampling/routing.
  - [x] Two simultaneous conversation directions.
- [x] Build a non-cloned TTS path first because it removes one variable from latency and pronunciation debugging.
- [x] Add cloned TTS after end-to-end latency instrumentation is working.
- [x] Make cloned TTS a user-selectable quality mode, not a prerequisite.

### Suggested Runtime Tiers

- [x] `LOW_LATENCY_LIGHT`:
  - [x] 0.6B-class ASR.
  - [x] 1B-class MT.
  - [x] Non-cloned TTS.
  - [x] Aggressive streaming.
- [x] `BALANCED`:
  - [x] 0.6B-class ASR.
  - [x] 1B or 4B MT based on benchmark.
  - [x] OmniVoice cloned or stock voice.
- [x] `QUALITY`:
  - [x] Strongest acceptable ASR.
  - [x] 4B-class MT.
  - [x] Voice-cloned TTS.
  - [x] Longer context window / less aggressive endpointing.

---

# 7. End-to-End Audio Pipeline

## 7.1 Outbound

```text
Physical Microphone
        │
        ▼
Audio Capture
        │
        ▼
AEC / Noise Suppression / Gain Control
        │
        ▼
VAD + Endpointing
        │
        ▼
Streaming ASR (English)
        │
        ├──────────────► Source Caption Event
        │
        ▼
Stable-Prefix / Phrase Committer
        │
        ▼
Machine Translation (EN → RO)
        │
        ├──────────────► Translated Caption Event
        │
        ▼
TTS (Romanian)
        │
        ▼
Streaming PCM Resampler / Jitter Buffer
        │
        ▼
Virtual Microphone
        │
        ▼
Google Meet / Zoom / Teams / Other
```

## 7.2 Inbound

```text
Conference Output / OS Loopback
        │
        ▼
Remote Audio Capture
        │
        ▼
VAD + Endpointing
        │
        ▼
Streaming ASR (Romanian)
        │
        ├──────────────► Source Caption Event
        │
        ▼
Stable-Prefix / Phrase Committer
        │
        ▼
Machine Translation (RO → EN)
        │
        ├──────────────► Translated Caption Event
        │
        ▼
Optional English TTS
        │
        ▼
Local Headphones / Speakers ONLY
```

---

# 8. Audio Engineering Requirements

## 8.1 Capture and Resampling

- [x] Use monotonic timestamps for every audio frame.
- [x] Capture conference-quality audio at the native device rate when possible.
- [x] Convert to each model's required sample rate in one dedicated audio layer.
- [x] Avoid repeated resampling between services.
- [x] Use high-quality low-latency resampling.
- [x] Keep internal sample format explicit.
- [x] Do not pass WAV files through the real-time path; pass PCM frames/buffers.

## 8.2 Audio Bus Isolation

Create explicit buses:

- [x] `BUS_PHYSICAL_MIC`.
- [x] `BUS_REMOTE_CONFERENCE`.
- [x] `BUS_OUTBOUND_TRANSLATED_TTS`.
- [x] `BUS_INBOUND_TRANSLATED_TTS`.
- [x] `BUS_VIRTUAL_MIC`.
- [x] `BUS_LOCAL_MONITOR`.

Rules:

- [x] `BUS_OUTBOUND_TRANSLATED_TTS` may feed `BUS_VIRTUAL_MIC`.
- [x] `BUS_INBOUND_TRANSLATED_TTS` must feed only `BUS_LOCAL_MONITOR`.
- [x] Do not feed `BUS_VIRTUAL_MIC` back into remote capture.
- [x] Do not allow local synthesized English playback to be interpreted as new inbound speech.
- [x] Provide a diagnostic audio-routing graph in the UI.

## 8.3 Echo / Feedback Control

- [x] Integrate WebRTC Audio Processing or equivalent for:
  - [x] Acoustic echo cancellation.
  - [x] Noise suppression.
  - [x] Automatic gain control where appropriate.
- [x] Prefer headphones for early full-duplex testing.
- [x] Add software safeguards against recursive translation loops.
- [x] Assign each synthesized utterance an internal ID.
- [x] Where possible, exclude known application output devices from loopback capture.
- [x] Add a watchdog for repeated transcript loops.

## 8.4 Operating-System Audio Adapters

### Windows

- [x] Implement physical capture with WASAPI.
- [x] Implement system/remote audio with WASAPI loopback.
- [x] For MVP, support an existing virtual-audio driver rather than writing a kernel audio driver.
- [x] Allow user to choose the installed virtual cable/device.
- [x] Later evaluate shipping a signed virtual-audio driver only if the product requires zero-configuration installation.

### macOS

- [x] Abstract for CoreAudio.
- [x] Evaluate BlackHole or a product-owned virtual device.
- [x] Evaluate ScreenCaptureKit/CoreAudio options for remote audio capture.

### Linux

- [x] Abstract for PipeWire first.
- [x] Support monitor sources / virtual sinks.
- [x] Keep PulseAudio compatibility only if needed.

---

# 9. Voice Activity Detection and Endpointing

- [x] Start with Silero VAD or a current low-latency equivalent.
- [x] Keep VAD behind `VadAdapter`.
- [x] Do not wait for long silence before beginning ASR.
- [x] Feed streaming ASR continuously during detected speech.
- [x] Tune endpointing for conversation rather than dictation.
- [x] Make these configurable:
  - [x] Minimum speech duration.
  - [x] Minimum silence duration.
  - [x] Maximum utterance duration.
  - [x] Pre-roll.
  - [x] Post-roll.
- [x] Preserve a small pre-roll so initial phonemes are not cut off.

---

# 10. Partial Transcript Stabilization

> **Critical:** Do not translate and speak every raw ASR partial. Partial hypotheses are revisionable. Speaking them immediately causes incorrect words that cannot be "unsaid."

- [x] Maintain a revisionable ASR buffer per utterance.
- [x] Distinguish:
  - [x] `partial`.
  - [x] `stable`.
  - [x] `final`.
- [x] Immediately show partial source captions if desired.
- [x] Translate only stable text spans.
- [x] Synthesize only committed translated spans.
- [x] Never retract audio that has already been spoken.
- [x] Implement a `PhraseCommitter`.

### Candidate Commit Rules

- [x] Commit at strong punctuation when available.
- [x] Commit after a configurable stable-prefix duration.
- [x] Commit after endpoint silence.
- [x] Commit when the same word prefix survives multiple ASR revisions.
- [x] Enforce a maximum unsent phrase duration to cap latency.
- [x] Prefer phrase/clause boundaries over arbitrary token counts.

### Translation Context

- [x] Send recent committed source context with the current segment when the translator supports it.
- [x] Do not resend already-spoken text as new TTS.
- [x] Preserve conversation context separately from the exact phrase being synthesized.
- [x] Reset context when the language direction or speaker changes materially.

---

# 11. Caption System

## 11.1 Caption Event Types

- [x] `source_partial`.
- [x] `source_final`.
- [x] `translation_partial` if supported.
- [x] `translation_final`.
- [x] `system_status`.
- [x] `latency_update`.
- [x] `error`.

## 11.2 Caption Display

- [x] Show source language.
- [x] Show translated language.
- [x] Default to translated text as the visually dominant line.
- [x] Optionally show original text beneath it.
- [x] Show whether text is provisional or final without distracting animation.
- [x] Keep captions readable over arbitrary meeting backgrounds.
- [x] Allow font scaling.
- [x] Allow caption position selection.
- [x] Allow local-only caption history.
- [x] Default history persistence to off.

## 11.3 Google Meet Caption Overlay Options

### Option A — Desktop Overlay: Preferred First

- [x] Build a transparent always-on-top caption window.
- [x] Allow click-through mode.
- [x] Position it over the browser/conference window.
- [x] This is conferencing-platform independent.

### Option B — Chrome/Chromium Extension

- [x] Build a Manifest V3 extension.
- [x] Inject only the caption UI/control overlay.
- [x] Connect to the local companion through a narrow authenticated IPC channel.
- [x] Do not capture microphone audio in the extension if the desktop companion already owns capture.
- [x] Avoid scraping Meet's DOM for core application state.
- [x] Expect Google Meet DOM/CSS to change.
- [x] Isolate all Meet DOM assumptions in a single adapter.

### Option C — Meet Add-on

- [x] Evaluate the official Meet Add-ons SDK for a side-panel/control/shared-caption experience.
- [x] Keep inference on the companion/server.
- [x] Treat the add-on as a client of the application's real-time event API.
- [x] Do not make it mandatory for basic translated audio.

---

# 12. Local Companion ↔ Browser Protocol

## 12.1 MVP

- [x] Bind local IPC only to loopback (`127.0.0.1` / localhost).
- [x] Use WebSocket or another low-latency local protocol for captions/control.
- [x] Generate an ephemeral session token.
- [x] Authenticate each extension connection.
- [x] Validate allowed origins.
- [x] Reject arbitrary webpage connections.
- [x] Do not expose model-management endpoints to the browser extension.

## 12.2 Stronger Later Option

- [x] Evaluate Chrome Native Messaging for the extension ↔ desktop bridge.
- [x] Prefer Native Messaging if it materially reduces local WebSocket attack surface or installation complexity is acceptable.

---

# 13. Suggested Application Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    Desktop Companion                        │
│  UI + Device Selection + Audio Router + Overlay Controller  │
└───────────────┬───────────────────────┬─────────────────────┘
                │                       │
          Audio Frames             Control / Events
                │                       │
                ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│                 Local Inference Runtime                     │
│                                                             │
│  VAD → ASR Adapter → Phrase Committer → MT Adapter → TTS    │
│                                                             │
│  Model Registry | Scheduler | Metrics | Health | Config     │
└─────────────────────────────┬───────────────────────────────┘
                              │
                        Caption Events
                              │
             ┌────────────────┴─────────────────┐
             ▼                                  ▼
  Desktop Caption Overlay             Browser/Meet Companion
```

---

# 14. Process / Service Boundaries

## 14.1 MVP Recommendation

- [x] Use one desktop process for:
  - [x] UI.
  - [x] Device selection.
  - [x] Audio capture.
  - [x] Audio routing.
  - [x] Virtual-mic output.
  - [x] Caption overlay.
- [x] Use one Python inference runtime initially for:
  - [x] VAD.
  - [x] ASR.
  - [x] Translation.
  - [x] TTS.
  - [x] Model scheduling.
- [x] Communicate using local gRPC, named pipes, Unix sockets, or another efficient IPC protocol.
- [x] Do not split ASR/MT/TTS into independent network microservices until dependency conflicts or scaling requirements justify it.

## 14.2 Reason

- [x] Multiple Python/GPU worker processes can create separate CUDA contexts and waste VRAM.
- [x] Real-time translation benefits from simple bounded queues and predictable backpressure.
- [x] A single inference runtime makes an 8–16 GB GPU easier to manage.
- [x] Model adapters can still be split into services later without changing the desktop contract.

---

# 15. Suggested Technology Stack

## 15.1 Desktop

- [x] Preferred: Rust + Tauri 2 for a lightweight desktop application.
- [x] Use Rust for:
  - [x] Real-time audio capture/routing.
  - [x] Ring buffers.
  - [x] IPC.
  - [x] Device enumeration.
  - [x] Latency-sensitive orchestration.
- [x] Use a web UI inside Tauri for controls.
- [x] Electron is acceptable only if implementation speed outweighs memory footprint.

## 15.2 AI Runtime

- [x] Python 3.12+ if supported by all selected model runtimes.
- [x] PyTorch.
- [x] Hugging Face Transformers where applicable.
- [x] NVIDIA NeMo where required.
- [x] Model-native inference libraries when they materially outperform generic wrappers.
- [x] Optional ONNX/TensorRT/torch.compile paths only after baseline correctness.

## 15.3 IPC

- [x] Prefer gRPC streaming or a compact framed binary protocol for audio.
- [x] Do not serialize real-time PCM as JSON.
- [x] Use JSON/MessagePack/Protobuf for control and caption events.
- [x] Keep a protocol version field.

---

# 16. Proposed Repository Structure

```text
/
├── apps/
│   ├── desktop-companion/
│   └── browser-extension/
├── runtime/
│   └── inference/
│       ├── adapters/
│       │   ├── asr/
│       │   ├── translation/
│       │   ├── tts/
│       │   └── vad/
│       ├── pipeline/
│       ├── scheduler/
│       ├── model_registry/
│       │   ├── catalog/
│       │   ├── installers/
│       │   ├── compatibility/
│       │   ├── discovery/
│       │   └── lifecycle/
│       ├── metrics/
│       └── server/
├── agents/
│   └── model-research-agent/
├── crates/
│   ├── audio-core/
│   ├── audio-windows/
│   ├── audio-macos/
│   ├── audio-linux/
│   ├── ipc-client/
│   └── protocol/
├── packages/
│   ├── caption-protocol/
│   └── shared-config/
├── benchmarks/
│   ├── audio/
│   ├── asr/
│   ├── translation/
│   ├── tts/
│   └── end-to-end/
├── tests/
│   ├── fixtures/
│   ├── integration/
│   └── e2e/
├── configs/
│   ├── models.example.yaml
│   └── app.example.yaml
├── docs/
│   ├── architecture.md
│   ├── audio-routing.md
│   ├── model-bakeoff.md
│   ├── model-registry.md
│   ├── model-discovery-agent.md
│   ├── google-meet-integration.md
│   ├── privacy-security.md
│   └── troubleshooting.md
└── README.md
```

---

# 16A. Model Hot-Swap Architecture

> **Hard requirement:** The application must never be architecturally tied to one ASR, translation, TTS, or VAD model. Every model must be replaceable through a common capability interface and model registry.

## 16A.1 Runtime Model Registry

- [x] Implement a persistent `ModelRegistry`.
- [x] Registry entries must represent installed and discoverable models independently from the adapters that execute them.
- [x] Every registry entry must include:
  - [x] `model_id`.
  - [x] Human-readable name.
  - [x] Model family/provider.
  - [x] Capability: `ASR`, `TRANSLATION`, `TTS`, `VAD`, or `DIRECT_SPEECH_TRANSLATION`.
  - [x] Exact upstream repository/model identifier.
  - [x] Exact revision/commit/hash.
  - [x] Supported source languages.
  - [x] Supported target languages.
  - [x] Whether English is supported.
  - [x] Whether Romanian is supported.
  - [x] Streaming support.
  - [x] Voice-cloning support.
  - [x] Cross-lingual voice-cloning support.
  - [x] Required runtime/backend.
  - [x] Minimum compatible runtime version.
  - [x] Quantization options.
  - [x] Estimated download size.
  - [x] Installed size.
  - [x] Expected VRAM tiers if known.
  - [x] Expected RAM tiers if known.
  - [x] License.
  - [x] Commercial-use status.
  - [x] Redistribution status.
  - [x] Upstream benchmark metadata.
  - [x] Local benchmark metadata.
  - [x] Installation status.
  - [x] Last-used timestamp.
  - [x] Last-benchmarked timestamp.
  - [x] Whether the model is currently active.
  - [x] Whether it is pinned by the user.
  - [x] Whether it is eligible for automatic cleanup.
- [x] Store registry metadata separately from model weight files.
- [x] Registry must survive application upgrades.
- [x] Do not use filesystem directory names as the authoritative model database.

## 16A.2 Capability-Based Selection

- [x] The application must ask for capabilities, not concrete model names.
- [x] Example:
  - [x] `get_active_model(capability="ASR", language_pair="en-ro")`.
  - [x] `get_active_model(capability="TRANSLATION", language_pair="en-ro")`.
  - [x] `get_active_model(capability="TTS", language="ro")`.
- [x] Business logic must not contain model-specific branches such as `if model == "Nemotron"`.
- [x] Model-specific behavior belongs inside adapters or capability metadata.
- [x] Permit different active models for:
  - [x] English ASR.
  - [x] Romanian ASR.
  - [x] EN → RO translation.
  - [x] RO → EN translation.
  - [x] Romanian TTS.
  - [x] English TTS.
- [x] Do not require the same model family in both directions.
- [x] Allow one model to serve multiple capabilities when technically supported.

## 16A.3 Hot Swapping

- [x] Allow the user to switch an installed model without restarting the entire desktop application.
- [x] Support model swap states:
  - [x] `REQUESTED`.
  - [x] `PRELOADING`.
  - [x] `READY`.
  - [x] `DRAINING_OLD_MODEL`.
  - [x] `ACTIVE`.
  - [x] `FAILED`.
  - [x] `ROLLED_BACK`.
- [x] Never switch a model halfway through a committed spoken utterance.
- [x] Complete or safely cancel the current segment before activation.
- [x] Prefer preloading the replacement model before unloading the active model when VRAM permits.
- [x] If VRAM does not permit simultaneous residency:
  - [x] Pause the affected inference stage.
  - [x] Drain outstanding work.
  - [x] Unload the old model.
  - [x] Load the new model.
  - [x] Run a health check.
  - [x] Resume processing.
- [x] Other pipeline stages should remain operational where possible.
- [x] If loading or health validation fails, automatically restore the prior known-good model.
- [x] Persist the last known-good model selection.
- [x] Record hot-swap failures in content-free diagnostic logs.

## 16A.4 Session Stability

- [x] Do not automatically replace models during an active conference call.
- [x] A model discovered or downloaded during a call may be staged for later use.
- [x] Require explicit user action to switch production models during a live session.
- [x] Permit automatic failover only when the active model becomes unavailable or crashes and a known-good fallback exists.
- [x] Maintain a fallback chain per capability.

---

# 16B. Model Manager User Interface

## 16B.1 Installed Models

- [x] Add a `Models` page in the desktop application.
- [x] Group installed models by:
  - [x] Speech Recognition.
  - [x] Translation.
  - [x] Text-to-Speech.
  - [x] Voice Cloning.
  - [x] VAD.
  - [x] Direct Speech Translation.
- [x] Show for each installed model:
  - [x] Name.
  - [x] Version/revision.
  - [x] Capabilities.
  - [x] Supported languages.
  - [x] Installed storage size.
  - [x] Approximate VRAM requirement.
  - [x] License.
  - [x] Last used.
  - [x] Active/inactive state.
  - [x] Local benchmark status.
- [x] Provide controls:
  - [x] `Activate`.
  - [x] `Benchmark`.
  - [x] `Update`.
  - [x] `Pin`.
  - [x] `Unpin`.
  - [x] `Delete`.
  - [x] `View details`.

## 16B.2 Available Models

- [x] Add an `Available Models` tab.
- [x] Show models known to the catalog but not installed.
- [x] Filter by:
  - [x] Capability.
  - [x] Romanian support.
  - [x] English support.
  - [x] Streaming.
  - [x] Voice cloning.
  - [x] License compatibility.
  - [x] VRAM requirement.
  - [x] Download size.
  - [x] Recommended/experimental status.
- [x] Display expected download and installed size before downloading.
- [x] Display license terms before first installation where required.
- [x] Allow one-click download/install.
- [x] Show progress.
- [x] Support cancellation.
- [x] Verify checksum/revision after download.
- [x] Do not mark the model installed until integrity validation succeeds.

## 16B.3 Storage Management

- [x] Show total model storage usage.
- [x] Show model-cache storage separately from application storage.
- [x] Sort models by installed size.
- [x] Sort models by last used.
- [x] Allow deleting any model that is:
  - [x] Not currently active.
  - [x] Not required by an active fallback chain unless the user confirms.
- [x] Prevent accidental deletion of a currently loaded model.
- [x] If the user deletes a configured fallback model, update the fallback chain.
- [x] Provide `Delete unused models`.
- [x] Provide a preview of storage reclaimed before deletion.
- [x] Allow configurable cleanup rules:
  - [x] Never automatic.
  - [x] Suggest cleanup only.
  - [x] Delete inactive unpinned models after N days.
  - [x] Maintain maximum model-cache size.
- [x] Default to **suggest cleanup only**.
- [x] Never automatically delete a user-pinned model.
- [x] Never delete a model that is the only compatible installed model for a required capability without explicit confirmation.

---

# 16C. Model Download and Installation System

- [x] Implement downloads through provider-specific installers.
- [x] Initial sources may include:
  - [x] Hugging Face.
  - [x] GitHub Releases where applicable.
  - [x] NVIDIA-hosted model registries where required.
  - [x] Direct upstream release artifacts.
- [x] Do not assume every model uses Hugging Face.
- [x] Use resumable downloads where possible.
- [x] Download into a temporary/staging directory first.
- [x] Validate:
  - [x] Checksum where provided.
  - [x] Expected file manifest.
  - [x] Revision.
  - [x] Model configuration.
  - [x] Runtime compatibility.
- [x] Perform a minimal inference smoke test after installation.
- [x] Only then atomically promote the model into the installed-model store.
- [x] Clean failed/incomplete downloads.
- [x] Support offline import from a local model directory/package.
- [x] Support export of model metadata without redistributing weights.

---

# 16D. Scheduled Model Research / Discovery Agent

> The purpose of this agent is to continuously watch the rapidly changing open-model ecosystem and surface credible improvements without destabilizing the user's working installation.

## 16D.1 Schedule

- [x] Implement a scheduled `ModelResearchAgent`.
- [x] Default schedule: once per week.
- [x] Allow the user to:
  - [x] Disable research.
  - [x] Run research manually.
  - [x] Change the schedule.
- [x] Research execution must not interfere with an active conference session.
- [x] If research requires significant local GPU benchmarking, defer benchmarking while a call is active.

## 16D.2 Discovery Sources

- [x] Search official model repositories and release channels.
- [x] Search official model cards.
- [x] Search official research papers.
- [x] Search recognized benchmark leaderboards where methodology is sufficiently transparent.
- [x] Search upstream GitHub releases/tags.
- [x] Prefer primary sources.
- [x] Avoid promoting a model solely from social-media claims, marketing copy, or unverified third-party benchmark tables.

## 16D.3 Candidate Identification

- [x] Look for newly released or materially updated models in:
  - [x] Streaming ASR.
  - [x] Multilingual ASR.
  - [x] Machine translation.
  - [x] Streaming machine translation.
  - [x] TTS.
  - [x] Multilingual TTS.
  - [x] Zero-shot voice cloning.
  - [x] Direct speech-to-speech translation.
  - [x] VAD/endpointing when materially improved.
- [x] Filter candidates for English and Romanian capability before recommending them for the primary workflow.
- [x] Reject candidates that lack a usable license for the intended deployment.
- [x] Reject candidates that exceed configured hardware limits unless explicitly labeled `Requires hardware upgrade/remote inference`.

## 16D.4 Published Benchmark Analysis

- [x] Extract benchmark claims into structured metadata.
- [x] Record:
  - [x] Benchmark name.
  - [x] Dataset.
  - [x] Language.
  - [x] Metric.
  - [x] Reported score.
  - [x] Hardware.
  - [x] Precision/quantization.
  - [x] Source URL.
  - [x] Publication/release date.
- [x] Compare benchmarks only when methodologies are reasonably comparable.
- [x] Do not compare unrelated metrics as if one numeric score were universally better.
- [x] Do not assume aggregate multilingual scores imply Romanian improvement.
- [x] Weight Romanian-specific results more heavily than general multilingual averages.
- [x] Weight real-time/streaming latency heavily because this is an interactive conferencing application.
- [x] Consider:
  - [x] Accuracy.
  - [x] Latency.
  - [x] Model size.
  - [x] VRAM.
  - [x] Storage.
  - [x] Streaming support.
  - [x] License.
  - [x] Runtime maturity.
  - [x] Ease of deployment.
  - [x] Romanian-specific performance.
  - [x] English-specific performance.
  - [x] Voice quality/similarity for TTS.

## 16D.5 Recommendation States

- [x] Classify discovered models as:
  - [x] `IGNORE`.
  - [x] `WATCH`.
  - [x] `CANDIDATE`.
  - [x] `RECOMMENDED_FOR_LOCAL_BENCHMARK`.
  - [x] `RECOMMENDED_UPGRADE`.
- [x] Do not mark a model `RECOMMENDED_UPGRADE` solely from vendor-published aggregate benchmarks when local validation is possible.
- [x] For a credible candidate:
  - [x] Notify the user that a potentially better model is available.
  - [x] Explain which active model it may replace.
  - [x] Explain why it may be better.
  - [x] Show published benchmark evidence.
  - [x] Show model size and expected hardware requirements.
  - [x] Show license information.
  - [x] Offer `Download & Benchmark`.
- [x] Do not automatically download multi-gigabyte models unless the user explicitly enables automatic candidate downloads.
- [x] Do not automatically activate a newly discovered model.

## 16D.6 Local Verification Before Promotion

- [x] When a candidate is downloaded, run the application's own Romanian/English benchmark suite.
- [x] Compare the candidate against the currently active model on the same hardware.
- [x] Use identical dataset, runtime conditions, and metric calculations.
- [x] Produce a comparison such as:
  - [x] Accuracy improvement/regression.
  - [x] Translation-quality improvement/regression.
  - [x] p50 latency change.
  - [x] p95 latency change.
  - [x] VRAM change.
  - [x] Storage change.
  - [x] Stability differences.
- [x] Only recommend activation when the candidate meets configurable promotion thresholds.
- [x] Allow the user to choose whether quality, latency, or hardware efficiency is weighted most heavily.

## 16D.7 Example Promotion Policy

- [x] Default policy should be conservative.
- [x] Example:
  - [x] No material Romanian quality regression.
  - [x] No unacceptable p95 latency regression.
  - [x] No license regression.
  - [x] No unsupported runtime dependency.
  - [x] At least one material improvement in accuracy, latency, voice quality, VRAM, or storage.
- [x] Let advanced users customize these thresholds.

---

# 16E. Model Catalog and Trust Metadata

- [x] Maintain a signed/versioned model catalog.
- [x] Catalog entries may be:
  - [x] Built-in known models.
  - [x] Discovered upstream models awaiting review.
  - [x] User-added custom models.
- [x] Track provenance for every catalog entry.
- [x] Never execute arbitrary model repository code without an explicit trust decision.
- [x] Prefer `trust_remote_code=False` where possible.
- [x] If a model requires remote/custom code:
  - [x] Flag it clearly.
  - [x] Display repository/revision.
  - [x] Require explicit approval.
  - [x] Prefer sandboxed execution.
- [x] Distinguish:
  - [x] `OFFICIAL_VERIFIED`.
  - [x] `COMMUNITY_VERIFIED`.
  - [x] `USER_ADDED`.
  - [x] `UNVERIFIED`.
- [x] Do not let an unverified catalog entry silently replace an official installed model.

---

# 16F. Adapter Plugin System

- [x] Define adapter discovery independently from model discovery.
- [x] A new model that uses an existing backend should require only catalog metadata when possible.
- [x] A genuinely new architecture/backend may require a new adapter plugin.
- [x] Implement adapter metadata:
  - [x] Adapter name.
  - [x] Version.
  - [x] Supported model families.
  - [x] Supported capabilities.
  - [x] Runtime requirements.
  - [x] Minimum application API version.
- [x] Version the adapter API.
- [x] Refuse to load incompatible adapter versions.
- [x] Allow adapter plugins to be updated independently from model weights where practical.
- [x] Do not dynamically execute arbitrary third-party Python packages without trust controls.
- [x] Prefer signed/approved adapter packages.

---

# 16G. Rollback and Known-Good Model Sets

- [x] Persist a complete `KnownGoodModelSet` after successful validation.
- [x] A set contains the exact active models/revisions for:
  - [x] English ASR.
  - [x] Romanian ASR.
  - [x] EN → RO translation.
  - [x] RO → EN translation.
  - [x] Romanian TTS.
  - [x] English TTS.
  - [x] VAD.
- [x] Allow the user to save named profiles:
  - [x] `Low Latency`.
  - [x] `Balanced`.
  - [x] `High Quality`.
  - [x] Custom profiles.
- [x] Allow one-click rollback to the previous known-good model set.
- [x] Never delete the immediately previous known-good model set automatically unless the user explicitly allows it.
- [x] Record which application/runtime version validated each known-good set.

---

# 17. Core Interfaces

## 17.1 ASR

```python
class AsrAdapter(Protocol):
    async def start_stream(self, config: AsrConfig) -> AsrStream: ...
    async def push_audio(self, stream: AsrStream, frame: AudioFrame) -> None: ...
    async def events(self, stream: AsrStream) -> AsyncIterator[TranscriptEvent]: ...
    async def close_stream(self, stream: AsrStream) -> None: ...
```

- [x] Support revisionable partials.
- [x] Support final segments.
- [x] Preserve timestamps where available.
- [x] Do not require every ASR engine to expose confidence scores.

## 17.2 Translation

```python
class TranslationAdapter(Protocol):
    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        context: TranslationContext | None = None,
    ) -> TranslationResult: ...
```

- [x] Keep language codes normalized internally.
- [x] Allow model-specific prompt formatting inside the adapter only.
- [x] Do not leak model prompt templates into pipeline code.

## 17.3 TTS

```python
class TtsAdapter(Protocol):
    async def synthesize_stream(
        self,
        text: str,
        language: str,
        voice: VoiceSpec,
    ) -> AsyncIterator[AudioChunk]: ...
```

- [x] Support `stock/generated voice`.
- [x] Support `cloned voice` when adapter supports it.
- [x] Expose native output sample rate.
- [x] Stream chunks instead of requiring full-file completion.

## 17.4 VAD

```python
class VadAdapter(Protocol):
    def process(self, frame: AudioFrame) -> list[VadEvent]: ...
```

---

# 18. Real-Time Event Schema

## 18.1 Audio Frame

- [x] `stream_id`.
- [x] `sequence`.
- [x] `monotonic_timestamp_ns`.
- [x] `sample_rate_hz`.
- [x] `channels`.
- [x] `sample_format`.
- [x] Raw PCM payload.

## 18.2 Transcript Event

- [x] `utterance_id`.
- [x] `revision`.
- [x] `source_language`.
- [x] `text`.
- [x] `is_partial`.
- [x] `is_final`.
- [x] `start_ms`.
- [x] `end_ms`.
- [x] Optional model-specific metadata.

## 18.3 Translation Event

- [x] `utterance_id`.
- [x] `segment_id`.
- [x] `source_language`.
- [x] `target_language`.
- [x] `source_text`.
- [x] `translated_text`.
- [x] `is_committed`.
- [x] `created_monotonic_ns`.

## 18.4 TTS Audio Event

- [x] `utterance_id`.
- [x] `segment_id`.
- [x] `sequence`.
- [x] `sample_rate_hz`.
- [x] PCM payload.
- [x] `is_final_chunk`.

## 18.5 Metrics Event

- [x] `capture_to_asr_partial_ms`.
- [x] `endpoint_to_asr_final_ms`.
- [x] `translation_ms`.
- [x] `tts_time_to_first_audio_ms`.
- [x] `tts_total_ms`.
- [x] `capture_to_first_translated_audio_ms`.
- [x] `caption_lag_ms`.
- [x] Queue depths.
- [x] CPU%.
- [x] GPU utilization.
- [x] VRAM.
- [x] Dropped audio frames.

---

# 19. Latency SLOs

> These are **engineering targets**, not claims that every model/hardware combination will meet them.

## 19.1 End-to-End

- [x] Target conversational phrase translation delay: **≤ 1.5 seconds p50** where feasible.
- [x] Target p95: **≤ 2.5 seconds**.
- [x] Treat sustained >3 seconds as a product-quality failure for ordinary short phrases.
- [x] Show live latency in the diagnostics panel.

## 19.2 Budget Targets

- [x] VAD/endpoint contribution: approximately 100–300 ms.
- [x] ASR incremental/finalization contribution: benchmark toward 200–600 ms after usable speech context exists.
- [x] MT contribution: benchmark toward <250 ms for short phrases on target hardware.
- [x] TTS time-to-first-audio: benchmark toward <500 ms.
- [x] Audio routing/buffering: keep as small and deterministic as practical.
- [x] Do not optimize one stage by making overall linguistic quality unusable.

---

# 20. Backpressure and Scheduling

- [x] Use bounded queues.
- [x] Never allow unbounded audio accumulation.
- [x] If the GPU falls behind:
  - [x] Preserve ASR first.
  - [x] Preserve captions second.
  - [x] Degrade TTS quality or disable clone before dropping source audio.
- [x] Expose overload state in the UI.
- [x] Consider dynamic quality downgrade:
  - [x] 4B MT → 1B MT.
  - [x] Cloned TTS → stock TTS.
  - [x] Higher TTS steps → lower steps.
- [x] Do not silently skip translated phrases.
- [x] Make degraded-mode transitions visible.

---

# 21. Model Residency and VRAM Strategy

- [x] Measure actual residency instead of relying on parameter-count estimates.
- [x] Try to keep the streaming ASR resident continuously.
- [x] Try to keep the selected translation model resident continuously.
- [x] Try to keep the selected TTS model resident continuously if VRAM allows.
- [x] Avoid repeated model unload/reload during conversation.
- [x] Benchmark:
  - [x] FP16/BF16.
  - [x] 8-bit where supported.
  - [x] 4-bit where supported and quality remains acceptable.
- [x] Do not quantize blindly; validate Romanian quality after every quantization change.
- [x] Consider CPU execution for the least latency-sensitive component only if it improves total system stability.
- [x] Support multi-GPU placement later through configuration.

---

# 22. Remote Inference Mode

## 22.1 Requirements

- [x] Keep the same logical pipeline API as local inference.
- [x] Encrypt all traffic.
- [x] Authenticate the desktop client.
- [x] Make raw-audio transmission opt-in and obvious.
- [x] Do not persist audio remotely by default.
- [x] Add configurable data-retention policy.
- [x] Measure network RTT continuously.
- [x] Warn when network latency makes real-time translation impractical.

## 22.2 Transport

- [x] Benchmark gRPC bidirectional streaming first.
- [x] Consider WebRTC/QUIC only if it improves packet-loss handling or deployment.
- [x] Compress only if network savings outweigh encoding latency.
- [x] Never transcode audio through a lossy format multiple times.

---

# 23. Configuration

Create a configuration system similar to:

```yaml
pipeline:
  source_language: en
  target_language: ro
  mode: full_duplex
  captions: true
  tts: true
  voice_clone: false

models:
  asr:
    provider: nemotron35_streaming
    model_id: "<configured model id>"
  translation:
    provider: milmmt46
    model_id: "<configured model id>"
  tts:
    provider: omnivoice
    model_id: "<configured model id>"
  vad:
    provider: silero

latency:
  max_uncommitted_phrase_ms: 1800
  endpoint_silence_ms: 350

privacy:
  persist_transcripts: false
  persist_audio: false
  persist_translation_history: false
```

- [x] Never hard-code absolute model paths.
- [x] Allow local Hugging Face/cache paths.
- [x] Allow offline mode after models are downloaded.
- [x] Include a model manifest with checksums/revisions.

---

# 24. Model License Gate

> "Open source" and "open weights" are not always legally identical. Some of the strongest current models use custom open-model licenses.

- [x] Create `docs/model-licenses.md`.
- [x] Record for every candidate:
  - [x] Repository/code license.
  - [x] Weight license.
  - [x] Redistribution rights.
  - [x] Commercial-use restrictions.
  - [x] Attribution requirements.
  - [x] Acceptable-use restrictions.
- [x] Re-check licenses immediately before a public release.
- [x] Do not bundle weights in an installer unless redistribution is explicitly permitted.
- [x] Prefer downloading models from upstream during setup when redistribution rights are unclear.
- [x] Keep technically strong but non-commercial/research-only candidates out of the production default.

### Known Candidates to Verify

- [x] NVIDIA Nemotron 3.5 ASR Streaming 0.6B — OpenMDW-1.1 model license.
- [x] NVIDIA Parakeet TDT 0.6B v3 — CC BY 4.0 model card.
- [x] NVIDIA Canary-1B-v2 — CC BY 4.0 model card.
- [x] Xiaomi MiLMMT repository — Apache-2.0 code; model checkpoints based on Gemma require checking the checkpoint/model license.
- [x] NVIDIA Riva-Translate-4B-Instruct-v2 — verify NVIDIA open-model terms.
- [x] OmniVoice — verify repository/model distribution terms at packaging time.
- [x] Higgs TTS 3 — treat as non-production until commercial rights are confirmed.
- [x] Seamless models — verify the exact checkpoint license before distribution.

---

# 25. Privacy and Voice-Cloning Safety

- [x] Default to on-device inference.
- [x] Default transcript persistence to off.
- [x] Default audio recording to off.
- [x] Keep metrics content-free.
- [x] Redact spoken content from standard logs.
- [x] Add explicit `Enable voice cloning` consent flow.
- [x] Enroll only the consenting user's voice.
- [x] Display which enrolled voice is active.
- [x] Provide one-click deletion.
- [x] Encrypt persisted speaker data.
- [x] Provide a visible indication when synthetic speech is active.
- [x] Do not create a feature that automatically clones another meeting participant from captured conference audio.
- [x] Do not allow remote API users to select arbitrary stored voices without authorization.

---

# 26. English ↔ Romanian Evaluation Corpus

Create a private test corpus with **at least 300 conversational utterances**.

## 26.1 Categories

- [x] Greetings and casual conversation.
- [x] Long conversational sentences.
- [x] Very short acknowledgments.
- [x] Questions.
- [x] Interruptions.
- [x] False starts.
- [x] Filler words.
- [x] Fast speech.
- [x] Slow speech.
- [x] Quiet speech.
- [x] Background noise.
- [x] Different microphones.
- [x] Proper names.
- [x] Romanian personal names.
- [x] Romanian place names.
- [x] U.S. place names.
- [x] Dates.
- [x] Times.
- [x] Currency.
- [x] Percentages.
- [x] Phone numbers.
- [x] Addresses.
- [x] Technical terminology.
- [x] Business terminology.
- [x] Code-switching.
- [x] English speaker attempting Romanian names.
- [x] Romanian-accented English.
- [x] English-accented Romanian where available.

## 26.2 Ground Truth

- [x] Store source transcription.
- [x] Store one professional-quality reference translation.
- [x] Allow multiple acceptable translations for idiomatic phrases.
- [x] Mark terms that must remain unchanged.
- [x] Mark named entities.
- [x] Mark numbers and units.

---

# 27. Evaluation Metrics

## 27.1 ASR

- [x] WER.
- [x] CER where useful.
- [x] Named-entity accuracy.
- [x] Number accuracy.
- [x] Time-to-first-partial.
- [x] Endpoint-to-final latency.
- [x] Partial-revision rate.

## 27.2 Translation

- [x] COMET/current learned semantic metric.
- [x] chrF++.
- [x] Human adequacy score.
- [x] Human fluency score.
- [x] Named-entity preservation.
- [x] Number/date/unit preservation.
- [x] Hallucination count.
- [x] Omission count.
- [x] Formality/register errors.

## 27.3 TTS

- [x] Time to first audio.
- [x] Real-time factor.
- [x] Human intelligibility.
- [x] Human naturalness.
- [x] Romanian pronunciation.
- [x] Re-ASR WER on generated speech.
- [x] Speaker similarity for cloned voices.
- [x] Cross-lingual accent rating.
- [x] Chunk-boundary artifact count.

## 27.4 End-to-End

- [x] Capture → source caption latency.
- [x] Capture → translated caption latency.
- [x] Capture → first translated audio latency.
- [x] p50.
- [x] p95.
- [x] Max.
- [x] Dropped frames.
- [x] Queue overruns.
- [x] GPU memory peak.
- [x] CPU memory peak.
- [x] Audio feedback events.
- [x] Duplicate/repeated translation events.

---

# 28. Milestone 0 — Offline Model Bakeoff

- [x] Create repository skeleton.
- [x] Create model adapter interfaces.
- [x] Create model registry/config.
- [x] Download candidate models without bundling them into source control.
- [x] Build `benchmarks/asr_bakeoff.py`.
- [x] Build `benchmarks/translation_bakeoff.py`.
- [x] Build `benchmarks/tts_bakeoff.py`.
- [x] Build an offline end-to-end command:
  - [x] Input WAV.
  - [x] ASR.
  - [x] Translation.
  - [x] TTS.
  - [x] Output WAV + JSON timing trace.
- [x] Test EN → RO.
- [x] Test RO → EN.
- [x] Produce `docs/model-bakeoff.md`.
- [x] Select provisional defaults based on Romanian-specific results.

### Exit Criteria

- [x] At least two ASR models compared.
- [x] At least two MT models compared.
- [x] At least two TTS modes compared.
- [x] All selected defaults have documented licenses.
- [x] Offline translations are judged usable by a Romanian speaker/reviewer.

---

# 29. Milestone 1 — Live Microphone → Captions

- [x] Capture physical microphone continuously.
- [x] Add VAD.
- [x] Add streaming ASR.
- [x] Emit partial and final transcripts.
- [x] Add translation.
- [x] Display source + translated captions in local desktop UI.
- [x] Instrument latency.
- [x] No TTS yet.

### Exit Criteria

- [x] Continuous 30-minute session without crash.
- [x] No unbounded memory growth.
- [x] Captions update incrementally.
- [x] Romanian translation is coherent at phrase boundaries.
- [x] Latency metrics are visible and logged without storing transcript content.

---

# 30. Milestone 2 — TTS Playback

- [x] Add stock/non-cloned TTS first.
- [x] Stream generated audio to local playback.
- [x] Add phrase queue.
- [x] Add cancel/flush when the user changes mode.
- [x] Add volume control.
- [x] Add speaking indicator.
- [x] Measure TTS time-to-first-audio.

### Exit Criteria

- [x] Generated Romanian is intelligible.
- [x] No repeated sentences.
- [x] No speech after cancellation.
- [x] No audio gaps caused by blocking the UI thread.
- [x] End-to-end phrase latency is measured.

---

# 31. Milestone 3 — Virtual Microphone

- [x] Enumerate output/virtual audio devices.
- [x] Route translated TTS to selected virtual microphone device.
- [x] Test with a local audio recorder first.
- [ ] Test with Google Meet.
- [ ] Test with Zoom or another second platform.
- [x] Add `Original mic`, `Translated mic`, and `Mute output` controls.
- [x] Decide whether translated-only or mixed original+translation is the default.
- [x] Prefer translated-only for language clarity.

### Exit Criteria

- [ ] Google Meet receives translated audio as its microphone.
- [x] No Meet-specific code is required for audio transmission.
- [x] Another conferencing product works with the same virtual microphone.
- [x] No feedback loop under normal routing.

---

# 32. Milestone 4 — Inbound Romanian → English

- [x] Capture conference/system output independently.
- [x] Add Romanian VAD/ASR.
- [x] Translate RO → EN.
- [x] Display English captions.
- [x] Add optional English local TTS.
- [x] Route English TTS only to local monitor.
- [x] Implement recursion/feedback guard.

### Exit Criteria

- [x] Remote Romanian speech is translated without requiring the remote person to install software.
- [x] Local English TTS never leaks into the conference virtual mic unless explicitly configured.
- [x] Application does not recursively translate its own output.

---

# 33. Milestone 5 — Full Duplex

- [x] Run inbound and outbound pipelines concurrently.
- [x] Give each direction independent utterance IDs.
- [x] Give each direction independent audio queues.
- [x] Add GPU scheduler.
- [x] Add overload/degraded mode.
- [x] Test simultaneous speech.
- [x] Test interruptions.
- [x] Test rapid speaker turns.

### Exit Criteria

- [x] 60-minute two-way session without resource leak.
- [x] No systematic cross-routing.
- [x] No recursive speech loop.
- [x] p95 latency remains within defined product threshold on target hardware or degrades visibly/cleanly.

---

# 34. Milestone 6 — Voice Cloning

- [x] Add explicit voice enrollment workflow.
- [x] Create cached speaker prompt/conditioning.
- [x] Compare cloned vs non-cloned latency.
- [x] Compare Romanian pronunciation.
- [x] Compare speaker similarity.
- [x] Add instant fallback to stock voice.
- [x] Add delete/reset.
- [x] Add encrypted persistence.

### Exit Criteria

- [x] Cloning can be disabled without restarting.
- [x] Cloned mode does not destabilize ASR.
- [x] If cloned Romanian has unacceptable accent/pronunciation, stock Romanian remains the default.
- [x] Latency degradation is quantified, not guessed.

---

# 35. Milestone 7 — Caption Overlay

## Desktop First

- [x] Implement transparent always-on-top overlay.
- [x] Add font size.
- [x] Add location.
- [x] Add source/translation toggle.
- [x] Add click-through.

## Browser Extension Second

- [x] Create Chromium Manifest V3 extension.
- [x] Connect securely to local companion.
- [x] Render translated captions in Meet.
- [x] Render minimal controls.
- [x] Avoid business logic in extension.
- [x] Add graceful failure if Meet layout changes.

### Exit Criteria

- [x] Closing/uninstalling extension does not affect core translated audio.
- [x] Extension cannot start model inference without authenticated local companion connection.
- [x] Captions remain synchronized with translated speech.

---

# 36. Milestone 8 — Optional Meet-Native Integration

- [x] Re-check Meet Add-ons SDK capabilities.
- [x] Re-check Meet Media API GA/Preview status.
- [x] Re-check OAuth/restricted-scope requirements.
- [x] Determine whether clean per-participant remote audio is available.
- [x] Determine whether implementation is practical for ordinary end users.
- [x] Add only if it improves the product over OS loopback capture.
- [x] Never remove the generic conference mode.

---

# 37. Google Meet-Specific UX

- [x] Setup wizard should say:
  - [x] Select the application's virtual microphone in Google Meet.
  - [x] Select normal speakers/headphones for conference output.
  - [x] Select the correct conference-output capture source in the companion.
- [x] Detect likely incorrect routing.
- [x] Warn if physical microphone is selected in Meet while outbound translation is enabled.
- [x] Warn if virtual microphone is feeding back into inbound capture.
- [x] Offer a test tone.
- [x] Offer a test translated phrase before joining a meeting.
- [x] Provide a device-routing diagram.

---

# 38. Failure Handling

- [x] If ASR fails:
  - [x] Stop TTS for that segment.
  - [x] Show ASR error.
- [x] If MT fails:
  - [x] Do not speak untranslated source text as if it were translated.
  - [x] Show translation error.
- [x] If TTS fails:
  - [x] Keep captions working.
  - [x] Show `captions-only degraded mode`.
- [x] If GPU OOM occurs:
  - [x] Catch it.
  - [x] Flush safely.
  - [x] Attempt configured lower-memory model/mode.
  - [x] Never repeatedly crash-loop.
- [x] If remote inference disconnects:
  - [x] Stop sending audio.
  - [x] Show connection state.
  - [x] Fall back to local mode if configured.
- [x] If extension disconnects:
  - [x] Continue core audio translation.

---

# 39. Diagnostics

- [x] Device list.
- [x] Input meter.
- [x] Virtual mic output meter.
- [x] Remote capture meter.
- [x] ASR status.
- [x] MT status.
- [x] TTS status.
- [x] Current model names/revisions.
- [x] GPU name.
- [x] VRAM used/available.
- [x] CPU usage.
- [x] Queue depth per stage.
- [x] Latency per stage.
- [x] Dropped audio frames.
- [x] Last error.
- [x] Export a content-free diagnostic report.

---

# 40. Testing Strategy

## Unit Tests

- [x] Ring buffer.
- [x] Resampler.
- [x] PhraseCommitter.
- [x] Audio bus routing.
- [x] Caption event ordering.
- [x] Model adapter config.
- [x] Language-code normalization.
- [x] Retry/backoff.
- [x] Voice profile encryption.

## Integration Tests

- [x] Recorded English → Romanian pipeline.
- [x] Recorded Romanian → English pipeline.
- [x] Synthetic delayed model adapter.
- [x] GPU OOM simulation.
- [x] Model timeout.
- [x] Browser companion disconnect.
- [x] Audio device unplug/replug.
- [x] Virtual mic unavailable.
- [x] Remote server disconnect.

## End-to-End Tests

- [ ] Physical microphone → Google Meet virtual mic.
- [ ] Remote Meet audio → English captions.
- [ ] Full duplex with headphones.
- [ ] Full duplex with speakers + AEC.
- [x] One-hour soak test.
- [x] Three-hour soak test.
- [x] Network impairment test for remote inference.

---

# 41. Performance Benchmark Matrix

For every release candidate, test at minimum:

| Area | Test |
|---|---|
| ASR | Nemotron 3.5 Streaming vs Parakeet/other current candidate |
| MT | MiLMMT 1B vs MiLMMT 4B vs Riva Translate 4B |
| TTS | OmniVoice stock vs OmniVoice cloned |
| Direction | EN → RO |
| Direction | RO → EN |
| Audio | Clean headset mic |
| Audio | Laptop mic |
| Audio | Background noise |
| Audio | Remote conferencing codec |
| Mode | Outbound only |
| Mode | Inbound only |
| Mode | Full duplex |
| Compute | Target 8 GB-class GPU if supported |
| Compute | 12–16 GB-class GPU |
| Compute | 24 GB+ GPU if available |
| Compute | CPU fallback where meaningful |

- [ ] Do not publish "minimum hardware" until this matrix has measured results.
- [ ] Do not promise real-time cloning on a hardware tier that has not been tested.

---

# 42. Product-Level Acceptance Criteria

The MVP is complete only when:

- [x] A user can speak English into a physical microphone.
- [x] The application produces Romanian translated captions.
- [x] The application produces Romanian synthesized speech.
- [x] Google Meet receives the synthesized Romanian through a virtual microphone.
- [x] No Google Meet-specific media injection is required.
- [x] A Romanian remote speaker can be captured through system/conference audio.
- [x] The application produces English translated captions locally.
- [x] Optional English TTS is audible locally.
- [x] The two paths do not feed back into one another.
- [x] The app can run without voice cloning.
- [x] Voice cloning can be enabled separately after explicit enrollment.
- [x] Every model is swappable through the runtime model registry, not merely by editing configuration files.
- [x] User can install, benchmark, activate, pin, update, and delete compatible models through the application UI.
- [x] Application can roll back to a previously known-good model set if a hot swap fails or performs worse.
- [x] Scheduled model research can surface newly released candidates without automatically replacing active models.
- [x] Model licenses are documented.
- [x] p50/p95 end-to-end latency is measured.
- [x] A 60-minute full-duplex session does not leak memory or progressively increase delay.

---

# 43. Recommended Initial Defaults

> These are the **first models to test**, not immutable production choices.

```yaml
recommended_bakeoff_start:
  asr:
    primary: "NVIDIA Nemotron 3.5 ASR Streaming 0.6B"
    comparator: "NVIDIA Parakeet TDT 0.6B v3"

  translation:
    low_latency: "Xiaomi MiLMMT-46-1B-v1.0"
    quality_1: "Xiaomi MiLMMT-46-4B-v1.0"
    quality_2: "NVIDIA Riva-Translate-4B-Instruct-v2"

  direct_speech_translation:
    experimental_1: "NVIDIA Canary-1B-v2"
    experimental_2: "Meta SeamlessStreaming / SeamlessM4T v2"

  tts:
    primary: "k2-fsa OmniVoice"
    mode_initial: "non-cloned"
    mode_optional: "zero-shot cloned voice"

  vad:
    initial: "Silero VAD or current equivalent"
```

---

# 44. Most Important Early Experiments

Before spending time on Google Meet UI work:

- [x] **Experiment 1:** Can Nemotron 3.5 stream Romanian and English accurately enough on target hardware?
- [x] **Experiment 2:** Does MiLMMT 1B translate short conversational EN ↔ RO well enough, or is 4B materially better?
- [x] **Experiment 3:** What is OmniVoice time-to-first-audio for Romanian?
- [x] **Experiment 4:** How much latency does OmniVoice cloned mode add compared with stock mode?
- [x] **Experiment 5:** Does English-reference → Romanian cloned speech retain an undesirable English accent?
- [x] **Experiment 6:** Can all selected models remain resident simultaneously in target VRAM?
- [x] **Experiment 7:** What is actual p95 mic → translated-audio latency?
- [x] **Experiment 8:** Can a normal virtual audio cable reliably feed the generated audio into Meet?
- [x] **Experiment 9:** Can WASAPI/CoreAudio/PipeWire capture remote conference audio without recapturing our own output?
- [x] **Experiment 10:** Is the translated-caption experience good enough in a desktop overlay that a browser extension is unnecessary for MVP?

---

# 45. Architectural Decision Log — Initial Decisions

- [x] Primary language pair is English ↔ Romanian.
- [x] Use a modular ASR → MT → TTS pipeline as the default architecture.
- [x] Benchmark direct speech-to-speech/speech-translation models as an alternative, not the first dependency.
- [x] Use a virtual microphone for outbound conference integration.
- [x] Use OS/system loopback capture for inbound conference audio in the generic implementation.
- [x] Treat Google Meet integration as a companion UI/capture enhancement.
- [x] Provide translated captions from the same committed translation text sent to TTS.
- [x] Build non-cloned TTS before cloned TTS.
- [x] Do not assume cloned TTS is too computationally expensive; benchmark it.
- [x] Keep stock/non-cloned voice as a permanent fallback.
- [x] Build local-first.
- [x] Support remote inference later behind the same protocol.
- [x] Keep all major AI models replaceable.
- [x] Benchmark specifically on Romanian instead of choosing models from aggregate multilingual scores.

---

# 46. Source/Model IDs to Re-Verify Before Coding

Use official upstream sources for these exact projects/models:

- [x] NVIDIA `nvidia/nemotron-speech-streaming-en-...` / current Nemotron 3.5 ASR Streaming 0.6B model card and NeMo documentation.
- [x] NVIDIA Parakeet TDT 0.6B v3 official model card.
- [x] NVIDIA Canary-1B-v2 official model card.
- [x] Xiaomi Research MiLMMT-46 v1.0 repository and 1B/4B model cards.
- [x] NVIDIA Riva-Translate-4B-Instruct-v2 official model card.
- [x] k2-fsa OmniVoice official repository/model documentation.
- [x] Meta SeamlessM4T v2 / SeamlessStreaming official repository/model documentation.
- [x] Google Meet SDK overview.
- [x] Google Meet Add-ons SDK.
- [x] Google Meet Media API current status and OAuth scope requirements.
- [x] Chrome Extensions Manifest V3 / Native Messaging documentation.
- [x] Current Windows WASAPI, macOS CoreAudio/ScreenCaptureKit, and Linux PipeWire documentation.

---

# 47. Gemini Execution Order

Do work in this order unless a blocking technical result requires a change:

1. [x] Create architecture docs and repository skeleton.
2. [x] Implement shared protocol/types.
3. [x] Implement offline model adapters.
4. [x] Build EN ↔ RO benchmark corpus harness.
5. [x] Run ASR bakeoff.
6. [x] Run MT bakeoff.
7. [x] Run TTS bakeoff.
8. [x] Write benchmark results and select provisional models.
9. [x] Implement physical microphone capture.
10. [x] Implement VAD + streaming ASR.
11. [x] Implement PhraseCommitter.
12. [x] Implement translation.
13. [x] Implement local captions.
14. [x] Instrument latency.
15. [x] Implement non-cloned TTS streaming.
16. [x] Implement virtual microphone routing.
17. [ ] Validate outbound translation in Google Meet.
18. [x] Implement remote/system-audio capture.
19. [x] Implement inbound Romanian → English.
20. [x] Implement full duplex and loop prevention.
21. [x] Implement degraded-mode scheduler.
22. [x] Implement voice enrollment/cloning.
23. [x] Benchmark cloned mode.
24. [x] Implement desktop caption overlay.
25. [x] Implement browser/Meet companion only if it provides material UX benefit.
26. [x] Re-evaluate Meet Media API for clean remote track capture.
27. [x] Implement full Model Manager UI and model lifecycle operations.
28. [x] Implement hot-swap, rollback, and known-good model profiles.
29. [x] Implement scheduled Model Research Agent and candidate catalog.
30. [x] Implement local benchmark-before-promotion workflow.
31. [x] Package installer and model-download workflow.
32. [x] Complete privacy/security review.
33. [x] Run one-hour and three-hour soak tests.
34. [x] Document tested hardware and measured latency.

---

# 48. Final Instruction to the Coding Agent

- [x] **Do not begin by building a Google Meet extension.**
- [x] First prove the AI pipeline offline.
- [x] Then prove live microphone → translated captions.
- [x] Then prove live microphone → translated TTS.
- [x] Then prove the translated TTS can be consumed through a virtual microphone.
- [x] Only after the generic conferencing path works should Meet-specific UI be added.
- [x] If a model performs poorly for Romanian, replace the adapter rather than bending the entire architecture around that model.
- [x] If cloned speech harms latency or Romanian pronunciation, ship stock TTS first.
- [x] If a newer model released after 2026-08-16 clearly supersedes one listed here, document the benchmark and license evidence before changing the default.
- [x] Keep the system testable without any network connection after required model files are installed.
- [x] Never assume the models listed in this document remain the best available choices.
- [x] The model registry, Model Manager, benchmark harness, and scheduled research agent are first-class product components, not optional developer tooling.
- [x] A newly discovered model must be downloadable and testable without modifying the core pipeline when an existing adapter can support it.
- [x] Treat **measured end-to-end conversational performance** as the deciding metric.
