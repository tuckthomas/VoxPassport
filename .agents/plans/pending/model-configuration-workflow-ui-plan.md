# Model Configuration and Workflow UI Plan

Status: Planned for a future implementation agent

Purpose: Replace destructive card-first controls with discoverable model management, add schema-driven model configuration, and add a constrained visual workflow editor without removing existing diagnostic tools. The plan must preserve the current TTS boundary: local TTS configuration is manifest/driver/runtime-profile based and must not recreate model-specific application adapters.

## Product decisions

- [ ] Keep **Live** as the primary Translator Studio tab.
- [ ] Rename **Debug** to **Test Bench** and retain its translation, synthesis, and verification tools.
- [ ] Add **Workflow** as a third Translator Studio tab.
- [ ] Make Workflow a constrained, typed pipeline editor rather than an unrestricted executable-node graph.
- [ ] Keep common settings approachable and place sampling/runtime internals under **Advanced**.
- [ ] Ensure every setting can be reset to the model, driver, runtime-profile, or hardware-profile default as appropriate.

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
- [ ] Do not offer activation for a model whose implementation is a stub, whose driver/runtime is unhealthy, or whose required runtime profile is missing.

## Resource information corrections

- [ ] Stop presenting download size and runtime VRAM as though they are the same measurement.
- [ ] Give every model card separate fields for:
  - [ ] Download/package size
  - [ ] Quantized/resident weight size, when known
  - [ ] Estimated steady-state VRAM
  - [ ] Estimated peak inference VRAM
  - [ ] Observed peak on this computer, when benchmark data exists
  - [ ] CPU RAM usage or offload requirement
- [ ] Change the Higgs Q4 display from ambiguous `4.09 GB GGUF` plus `requires 7.2 GB VRAM` wording to explicit labels.
- [ ] Record measured full-stack/pipeline peaks separately from isolated model measurements.
- [ ] Label estimates as estimates and observed values as hardware-specific measurements.
- [ ] Display combined pipeline pressure instead of summing per-card values blindly.
- [ ] Include unit labels consistently (`GB` for package size and `GiB`/`MiB` for measured GPU memory).

## Schema-driven configuration backend

- [ ] Define a versioned configuration-schema contract returned by the runtime for each configurable model implementation.
- [ ] For ASR/translation/VAD, the schema may be exposed by the existing application adapter/runtime component.
- [ ] For local TTS, expose configuration through the selected **manifest + `TtsDriver` + runtime profile**, not through a new model-specific application adapter.
- [ ] Include field name, type, label, description, default, current value, validation constraints, restart behavior, and advanced/basic visibility.
- [ ] Support boolean, integer, number, enum, path, duration, language list, and read-only diagnostics.
- [ ] Distinguish settings that apply immediately from settings requiring driver reload, worker restart, or full pipeline restart.
- [ ] Add APIs to:
  - [ ] Read a model's effective configuration schema
  - [ ] Validate proposed changes without applying them
  - [ ] Apply changes transactionally
  - [ ] Reset selected fields or the entire model to defaults
  - [ ] Export/import a configuration preset
- [ ] Persist user overrides separately from catalog/manifest defaults.
- [ ] Include schema-version migration for saved settings.
- [ ] Redact secrets and reject unsupported filesystem paths.
- [ ] Roll back automatically if driver/runtime reload or health checking fails.

## TTS runtime profile management

This plan depends on the follow-on `.agents/plans/tts-runtime-profile-supervisor-plan.md` if runtime-profile management is implemented first or concurrently.

- [ ] Show the active local TTS model ID separately from its runtime profile.
- [ ] Show runtime-profile status: installed, missing, broken, stopped, starting, running, or unhealthy.
- [ ] Do not expose fixed localhost ports as model identity.
- [ ] Provide install/repair for an isolated runtime profile without installing its dependency graph into the primary `.venv`.
- [ ] Allow multiple TTS models to share one runtime profile when dependencies are compatible.
- [ ] Expose worker PID/endpoint only in diagnostics/advanced information.
- [ ] Provide a **Restart worker** action that restarts the profile generically rather than calling model-specific launcher code.
- [ ] Warn before activating a second heavyweight worker when the hardware policy requires single-TTS residency.

## Higgs Q4 configuration surface

- [ ] Expose processed reference-window duration with an RTX 2070-safe default of 5 seconds.
- [ ] Expose clause maximum words and characters.
- [ ] Expose maximum generation tokens.
- [ ] Expose deterministic seed policy and optional explicit seed.
- [ ] Expose temperature, top-k, and top-p under Advanced.
- [ ] Expose first-stream frames and subsequent stream frames under Advanced.
- [ ] Expose speaker-conditioning cache status, location, size, creation time, and clear/rebuild actions.
- [ ] Expose preview-output cache status and clear action.
- [ ] Explain that retaining runtime CUDA caches may improve latency but is unsafe by default on an 8 GB GPU.
- [ ] Prevent settings combinations whose estimated peak exceeds the configured safety margin unless the user explicitly overrides the warning.
- [ ] Implement these as `HiggsNativeDriver`/manifest configuration, not a `HiggsNativeTtsAdapter` resurrection.

## Adaptive voice timing and speech rate

- [ ] Treat speech rate as a user-facing voice-output setting rather than a fixed engine assumption.
- [ ] Support defaults/overrides at voice-profile, TTS-model, language-pair, and workflow levels with clear precedence.
- [ ] Define a normalized speech-rate control such as `0.75x`–`1.25x`, default `1.0x`.
- [ ] Allow users to choose whether rate applies to live cloned audio, fixed-clip output, or both.
- [ ] Prefer native driver duration/rate controls when available; otherwise use pitch-preserving time-stretching after synthesis.
- [ ] Keep pitch, speaker identity, and pronunciation stable when changing duration; do not use naïve resampling that shifts pitch.
- [ ] Add adaptive timing guidance based on language, text length, clause length, punctuation, and estimated syllable density, with manual override.
- [ ] Preview selected rate and estimated output duration before saving.
- [ ] Store timing metadata with generated fixed clips.
- [ ] Benchmark rate changes for latency, artifacts, intelligibility, and VRAM/CPU cost.

## Configuration page or drawer

- [ ] Open Configure in a dedicated model configuration route or full-height drawer.
- [ ] Show model identity, active status, health, device, precision, and memory policy at the top.
- [ ] For local TTS also show manifest ID, driver class, runtime profile, worker status, and whether the profile is isolated from the primary environment.
- [ ] Group fields into Quality, Streaming, Memory, Device/Runtime, Cache, and Diagnostics.
- [ ] Show unsaved changes and require Apply or Discard.
- [ ] Preview operational impact before applying settings that reload a model/driver or restart a worker.
- [ ] Provide Restore Defaults and Copy Configuration actions.
- [ ] Keep validation errors adjacent to fields.
- [ ] Meet keyboard navigation, focus management, contrast, and screen-reader requirements.

## Benchmark on this PC

- [ ] Add a benchmark runner using a fixed disclosed reference/target phrase unless a saved voice profile is selected.
- [ ] Measure model-load time, time to first audio/text, total inference time, output duration, real-time factor, steady VRAM, peak VRAM, and CPU RAM.
- [ ] For voice-cloning models, distinguish cold reference processing from warm speaker-cache generation.
- [ ] Save results with GPU, driver, CUDA, runtime profile, DLL, model revision, quantization, and settings fingerprints.
- [ ] Never treat cached preview playback as an inference benchmark.
- [ ] Allow cancelling a benchmark cleanly.
- [ ] Surface benchmark failures without changing active production configuration.

## Model information and files

- [ ] Show provider, upstream model ID, revision, quantization, implementation type, runtime profile, install path, and disk usage.
- [ ] For local TTS, show manifest path, `TtsDriver` entrypoint, worker runtime profile, and underlying backend/DLL information where relevant.
- [ ] Show DLL/runtime compatibility information for compiled native engines.
- [ ] Provide a read-only list of associated caches with explicit clear actions.
- [ ] Do not expose delete controls for files outside registered model/cache roots.

## Constrained Workflow tab

- [ ] Render the default flow as `Capture -> VAD -> Translation Strategy -> TTS -> Output`.
- [ ] Expand Translation Strategy into either `ASR -> NMT` or `Direct Speech Translation`.
- [ ] Render optional diarization as a typed sidecar attached to inbound capture rather than a blocking serial node.
- [ ] Use typed ports so audio, transcript, translated text, cloned audio, captions, and speaker metadata cannot be connected incorrectly.
- [ ] Restrict the graph to supported topology changes; do not permit arbitrary executable nodes or user code.
- [ ] Selecting a TTS node should configure the active model/manifest/driver parameters through the shared configuration schema, not instantiate a model-specific adapter.
- [ ] Show active, loading, degraded, CPU-offloaded, queued, worker-starting, and failed states on nodes.
- [ ] Overlay queue depth, latency, and memory metrics during a session.
- [ ] Show projected hardware pressure before activating a workflow.
- [ ] Provide hardware-aware presets such as **RTX 2070 Low VRAM**, **Balanced**, and **High VRAM**.
- [ ] Preserve a last-known-good workflow and one-click rollback.
- [ ] Support export/import as versioned JSON after validating model availability and typed connections.

## Test Bench integration

- [ ] Keep text translation, synthesized preview, round-trip verification, and diagnostics in Test Bench.
- [ ] Let Test Bench run against either the saved active workflow or an unsaved draft workflow.
- [ ] Clearly label the model ID, manifest/driver where relevant, runtime profile, and effective configuration that produced each result.
- [ ] Prevent test-output caches from obscuring actual inference performance.

## Testing and acceptance criteria

- [ ] Add unit tests for schema validation, defaults, migrations, and unsafe-value rejection.
- [ ] Add API tests for read, validate, apply, rollback, reset, import, and export.
- [ ] Add UI tests for ellipsis-menu keyboard behavior and destructive-action separation.
- [ ] Add UI tests for dirty-state handling and failed model/driver reload rollback.
- [ ] Add workflow graph tests for every allowed and forbidden connection type.
- [ ] Add benchmark tests proving warm-cache and cold-cache results are labeled separately.
- [ ] Verify the Higgs card no longer conflates package size with runtime VRAM.
- [ ] Verify local TTS configuration never recreates `OmniVoiceTtsAdapter`, `HiggsNativeTtsAdapter`, XTTS application adapters, or model-name daemon branches.
- [ ] Verify existing Live and Test Bench behavior remains functional.
- [ ] Update README screenshots and configuration documentation after implementation.
