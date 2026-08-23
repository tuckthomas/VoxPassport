# Model Configuration and Workflow UI Plan

Status: Planned for a future implementation agent

Purpose: Replace destructive card-first controls with discoverable model management, add schema-driven model configuration, and add a constrained visual workflow editor without removing existing diagnostic tools. The plan must preserve the current TTS boundary: local TTS configuration is model-manifest/driver/backend-runtime/runtime-profile based and must not recreate model-specific application adapters or process wiring.

## Product decisions

- [ ] Keep **Live** as the primary Translator Studio tab.
- [ ] Rename **Debug** to **Test Bench** and retain its translation, synthesis, and verification tools.
- [ ] Add **Workflow** as a third Translator Studio tab.
- [ ] Make Workflow a constrained, typed pipeline editor rather than an unrestricted executable-node graph.
- [ ] Keep common settings approachable and place sampling/runtime internals under **Advanced**.
- [ ] Ensure every setting can be reset to the model, driver, backend-runtime, runtime-profile, or hardware-profile default as appropriate.

## Active Engines card actions

- [ ] Replace each card's standalone delete icon with an accessible vertical-ellipsis action button.
- [ ] Give the ellipsis button an accessible name such as `Actions for Higgs TTS 3 Q4 Native`.
- [ ] Add a keyboard-navigable menu with these actions in this order:
  - [ ] Configure
  - [ ] Benchmark on this PC
  - [ ] View model information and files
  - [ ] Uninstall, separated visually and styled as destructive
- [ ] Close the menu on Escape, outside click, focus loss, or completion of an action.
- [ ] Preserve a confirmation step for uninstall and identify the exact files and caches that will be removed.
- [ ] Show **Active** rather than **Enable** on the currently active card.
- [ ] Do not offer activation for a model whose implementation is a stub, whose driver/runtime is unhealthy, or whose required runtime profile/backend runtime is missing.

## Resource information corrections

- [ ] Stop presenting download size and runtime VRAM as though they are the same measurement.
- [ ] Give every model card separate fields for download/package size, resident weight size when known, estimated steady VRAM, estimated peak VRAM, observed peak on this computer, and CPU RAM/offload requirement.
- [ ] Change the Higgs Q4 display from ambiguous `4.09 GB GGUF` plus `requires 7.2 GB VRAM` wording to explicit labels.
- [ ] Record measured full-stack/pipeline peaks separately from isolated model measurements.
- [ ] Label estimates as estimates and observed values as hardware-specific measurements.
- [ ] Display combined pipeline pressure instead of summing per-card values blindly.

## Schema-driven configuration backend

- [ ] Define a versioned configuration-schema contract returned by the runtime for each configurable model implementation.
- [ ] For ASR/translation/VAD, expose configuration through the existing capability adapter/runtime component.
- [ ] For local TTS, expose configuration through the selected model manifest + `TtsDriver` + optional reusable backend runtime + runtime profile.
- [ ] Include field type, label, description, default/current value, validation constraints, restart behavior, and advanced/basic visibility.
- [ ] Distinguish model-specific settings from backend-family deployment settings and dependency-profile settings.
- [ ] Add APIs to read, validate, apply, reset, export, and import model configuration transactionally.
- [ ] Persist user overrides separately from catalog/manifest/backend-runtime defaults.
- [ ] Include schema-version migration for saved settings.
- [ ] Redact secrets and reject unsupported filesystem paths.
- [ ] Roll back automatically if driver/backend/worker reload or health checking fails.

## TTS runtime management

This plan depends on the implemented/refined architecture tracked in:

- `.agents/plans/in-progress/generic-tts-plugin-architecture-plan.md`
- `.agents/plans/in-progress/tts-runtime-profile-supervisor-plan.md`
- `.agents/plans/in-progress/tts-backend-runtime-catalog-plan.md`

- [ ] Show active local TTS model ID separately from its worker runtime profile and optional backend runtime ID.
- [ ] Show runtime-profile status: installed, missing, broken, stopped, starting, running, or unhealthy.
- [ ] Show managed backend status separately when a model uses a reusable backend runtime.
- [ ] Do not expose fixed localhost ports as model identity.
- [ ] Provide install/repair for an isolated runtime profile without installing its dependency graph into the primary `.venv`.
- [ ] Allow multiple TTS models to share one runtime profile and/or backend runtime when compatible.
- [ ] Expose worker/backend PIDs and ephemeral endpoints only in diagnostics/advanced information.
- [ ] Provide generic **Restart worker/backend** actions through the supervisor rather than model-specific launch code.
- [ ] Warn before activating a second heavyweight runtime when the hardware policy requires single-TTS residency.

## Higgs Q4 configuration surface

- [ ] Expose processed reference-window duration with an RTX 2070-safe default of 5 seconds.
- [ ] Expose clause maximum words/characters and generation-token limits.
- [ ] Expose deterministic seed policy and optional explicit seed.
- [ ] Expose temperature, top-k, and top-p under Advanced.
- [ ] Expose first-stream/subsequent stream frames under Advanced.
- [ ] Expose speaker-conditioning cache status, location, size, creation time, and clear/rebuild actions.
- [ ] Expose preview-output cache status and clear action.
- [ ] Explain runtime CUDA cache latency/memory tradeoffs.
- [ ] Prevent settings combinations whose estimated peak exceeds the configured safety margin unless the user explicitly overrides the warning.
- [ ] Implement these as `HiggsNativeDriver`/manifest configuration, not a `HiggsNativeTtsAdapter` resurrection.

## Adaptive voice timing and speech rate

- [ ] Treat speech rate as a user-facing voice-output setting.
- [ ] Support defaults/overrides at voice-profile, TTS-model, language-pair, and workflow levels with clear precedence.
- [ ] Define a normalized rate control with a sensible default.
- [ ] Prefer native driver duration/rate controls when available; otherwise use pitch-preserving time-stretching after synthesis.
- [ ] Keep pitch, speaker identity, and pronunciation stable when changing duration.
- [ ] Add adaptive timing guidance based on language, text length, clause length, punctuation, and estimated syllable density.
- [ ] Preview selected rate and estimated duration before saving.
- [ ] Benchmark rate changes for latency, artifacts, intelligibility, and resource cost.

## Configuration page or drawer

- [ ] Open Configure in a dedicated model configuration route or full-height drawer.
- [ ] Show model identity, active status, health, device, precision, and memory policy at the top.
- [ ] For local TTS show manifest ID, driver class, worker runtime profile, optional backend runtime ID/profile, and supervised worker/backend state.
- [ ] Group fields into Quality, Streaming, Memory, Device/Runtime, Cache, Backend, and Diagnostics.
- [ ] Show unsaved changes and require Apply or Discard.
- [ ] Preview operational impact before applying settings that reload a model/driver/backend or restart a worker.
- [ ] Provide Restore Defaults and Copy Configuration actions.
- [ ] Keep validation errors adjacent to fields.
- [ ] Meet keyboard navigation, focus management, contrast, and screen-reader requirements.

## Benchmark on this PC

- [ ] Add a benchmark runner using a fixed disclosed reference/target phrase unless a saved voice profile is selected.
- [ ] Measure model-load time, first output, total inference time, output duration, RTF, steady/peak VRAM, and CPU RAM.
- [ ] For voice cloning distinguish cold reference processing from warm speaker-cache generation.
- [ ] Save GPU, driver, CUDA, runtime profile, backend runtime, DLL/server, model revision, quantization, and settings fingerprints.
- [ ] Never treat cached preview playback as an inference benchmark.
- [ ] Allow cancelling a benchmark cleanly.
- [ ] Surface benchmark failures without changing active production configuration.

## Model information and files

- [ ] Show provider, upstream model ID, revision, quantization, implementation type, runtime profile, install path, and disk usage.
- [ ] For local TTS show model manifest path, `TtsDriver` entrypoint, optional backend runtime definition, worker/backend profiles, and underlying backend/DLL information.
- [ ] Show DLL/runtime compatibility information for compiled native engines.
- [ ] Provide a read-only list of associated caches with explicit clear actions.
- [ ] Do not expose delete controls for files outside registered model/cache roots.

## Constrained Workflow tab

- [ ] Render the default flow as `Capture -> VAD -> Translation Strategy -> TTS -> Output`.
- [ ] Expand Translation Strategy into either `ASR -> NMT` or `Direct Speech Translation`.
- [ ] Render optional diarization as a typed sidecar attached to inbound capture rather than a blocking serial node.
- [ ] Use typed ports so audio, transcript, translated text, cloned audio, captions, and speaker metadata cannot be connected incorrectly.
- [ ] Restrict the graph to supported topology changes; do not permit arbitrary executable nodes or user code.
- [ ] Selecting a TTS node should configure the model manifest/driver/runtime settings through the shared configuration schema, not instantiate a model-specific adapter.
- [ ] Show active, loading, degraded, CPU-offloaded, queued, worker/backend-starting, and failed states on nodes.
- [ ] Overlay queue depth, latency, and memory metrics during a session.
- [ ] Show projected hardware pressure before activating a workflow.
- [ ] Provide hardware-aware presets such as **RTX 2070 Low VRAM**, **Balanced**, and **High VRAM**.
- [ ] Preserve a last-known-good workflow and one-click rollback.
- [ ] Support export/import as versioned JSON after validating model availability and typed connections.

## Test Bench integration

- [ ] Keep text translation, synthesized preview, round-trip verification, and diagnostics in Test Bench.
- [ ] Let Test Bench run against either the saved active workflow or an unsaved draft workflow.
- [ ] Clearly label model ID, driver, runtime profile, backend runtime where relevant, and effective configuration for each result.
- [ ] Prevent test-output caches from obscuring actual inference performance.

## Testing and acceptance criteria

- [ ] Add unit tests for schema validation, defaults, migrations, and unsafe-value rejection.
- [ ] Add API tests for read, validate, apply, rollback, reset, import, and export.
- [ ] Add UI tests for ellipsis-menu keyboard behavior and destructive-action separation.
- [ ] Add UI tests for dirty-state handling and failed runtime reload rollback.
- [ ] Add workflow graph tests for every allowed and forbidden connection type.
- [ ] Add benchmark tests proving warm-cache and cold-cache results are labeled separately.
- [ ] Verify the Higgs card no longer conflates package size with runtime VRAM.
- [ ] Verify local TTS configuration never recreates concrete TTS application adapters, model-owned process topology, or model-name daemon/supervisor branches.
- [ ] Verify existing Live and Test Bench behavior remains functional.
- [ ] Update README screenshots and configuration documentation after implementation.
