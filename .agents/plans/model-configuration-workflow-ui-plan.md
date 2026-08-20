# Model Configuration and Workflow UI Plan

Status: Planned for a future implementation agent

Purpose: Replace destructive card-first controls with discoverable model management, add schema-driven model configuration, and add a constrained visual workflow editor without removing the existing diagnostic tools.

## Product decisions

- [ ] Keep **Live** as the primary Translator Studio tab.
- [ ] Rename **Debug** to **Test Bench** and retain its translation, synthesis, and verification tools.
- [ ] Add **Workflow** as a third Translator Studio tab.
- [ ] Make Workflow a constrained, typed pipeline editor rather than an unrestricted ComfyUI clone.
- [ ] Keep common settings approachable and place sampling/runtime internals under an **Advanced** section.
- [ ] Ensure every setting can be reset to the model or hardware-profile default.

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
- [ ] Do not offer activation for an adapter that is a stub, unhealthy, incompatible, or missing runtime dependencies.

## Resource information corrections

- [ ] Stop presenting download size and runtime VRAM as though they are the same measurement.
- [ ] Give every model card separate fields for:
  - [ ] Download/package size
  - [ ] Quantized or resident weight size, when known
  - [ ] Estimated steady-state VRAM
  - [ ] Estimated peak inference VRAM
  - [ ] Observed peak on this computer, when benchmark data exists
  - [ ] CPU RAM usage or offload requirement
- [ ] Change the Higgs Q4 display from the ambiguous `4.09 GB GGUF` plus `requires 7.2 GB VRAM` wording to explicit labels.
- [ ] Record that the RTX 2070 test observed approximately 5.97 GiB total resident stack usage and 7.54 GiB total pipeline peak usage; do not mislabel these as isolated model-only measurements.
- [ ] Label estimates as estimates and observed values as hardware-specific measurements.
- [ ] Display combined pipeline pressure instead of summing per-card values blindly.
- [ ] Include unit labels consistently (`GB` for package size and `GiB` or `MiB` for measured GPU memory).

## Schema-driven configuration backend

- [ ] Define a versioned configuration-schema contract returned by the runtime for each adapter.
- [ ] Include field name, type, label, description, default, current value, validation constraints, restart behavior, and advanced/basic visibility.
- [ ] Support schema field types for boolean, integer, number, enum, path, duration, language list, and read-only diagnostics.
- [ ] Distinguish settings that apply immediately from settings requiring adapter reload or full pipeline restart.
- [ ] Add APIs to:
  - [ ] Read a model's configuration schema and effective values
  - [ ] Validate proposed changes without applying them
  - [ ] Apply changes transactionally
  - [ ] Reset selected fields or the entire model to defaults
  - [ ] Export and import a configuration preset
- [ ] Persist user overrides separately from catalog defaults.
- [ ] Include schema version migration for saved settings.
- [ ] Redact secrets and reject unsupported filesystem paths.
- [ ] Roll back automatically if adapter reload or health checking fails.

## Higgs Q4 configuration surface

- [ ] Expose the processed reference-window duration with an RTX 2070-safe default of 5 seconds.
- [ ] Expose clause maximum words and characters.
- [ ] Expose maximum generation tokens.
- [ ] Expose deterministic seed policy and an optional explicit seed.
- [ ] Expose temperature, top-k, and top-p under Advanced.
- [ ] Expose first-stream frames and subsequent stream frames under Advanced.
- [ ] Expose speaker-conditioning cache status, location, size, creation time, and clear/rebuild actions.
- [ ] Expose preview-output cache status and clear action.
- [ ] Explain that retaining runtime CUDA caches may improve latency but is unsafe by default on an 8 GB GPU.
- [ ] Prevent settings combinations whose estimated peak exceeds the configured safety margin unless the user explicitly overrides the warning.

## Configuration page or drawer

- [ ] Open Configure in a dedicated model configuration route or full-height drawer.
- [ ] Show model identity, active status, adapter health, device, precision, and current memory policy at the top.
- [ ] Group fields into Quality, Streaming, Memory, Device/Runtime, Cache, and Diagnostics.
- [ ] Show unsaved changes and require Apply or Discard.
- [ ] Preview the operational impact before applying settings that reload a model.
- [ ] Provide Restore Defaults and Copy Configuration actions.
- [ ] Keep validation errors adjacent to their fields.
- [ ] Meet keyboard navigation, focus management, contrast, and screen-reader requirements.

## Benchmark on this PC

- [ ] Add a benchmark runner that uses a fixed, disclosed reference and target phrase unless the user selects a saved voice profile.
- [ ] Measure model-load time, time to first audio/text, total inference time, output duration, real-time factor, steady VRAM, peak VRAM, and CPU RAM.
- [ ] For voice-cloning models, distinguish cold reference processing from warm speaker-cache generation.
- [ ] Save benchmark results with GPU, driver, CUDA, runtime, DLL, model revision, quantization, and settings fingerprints.
- [ ] Never treat cached preview playback as an inference benchmark.
- [ ] Allow cancelling a benchmark cleanly.
- [ ] Surface benchmark failures without changing the active production configuration.

## Model information and files

- [ ] Show provider, upstream model ID, revision, quantization, adapter, runtime, install path, and disk usage.
- [ ] Show DLL/runtime compatibility information for compiled native engines.
- [ ] Provide a read-only list of associated caches with explicit clear actions.
- [ ] Do not expose delete controls for files outside the registered model/cache roots.

## Constrained Workflow tab

- [ ] Render the default flow as `Capture -> VAD -> Translation Strategy -> TTS -> Output`.
- [ ] Expand Translation Strategy into either `ASR -> NMT` or `Direct Speech Translation`.
- [ ] Render optional diarization as a typed sidecar attached to inbound capture rather than a blocking serial node.
- [ ] Use typed ports so audio, transcript, translated text, cloned audio, captions, and speaker metadata cannot be connected incorrectly.
- [ ] Restrict the graph to supported topology changes; do not permit arbitrary executable nodes or user code.
- [ ] Open the same schema-driven configuration surface when a model node is selected.
- [ ] Show active, loading, degraded, CPU-offloaded, queued, and failed states on nodes.
- [ ] Overlay live queue depth, latency, and memory metrics during a session.
- [ ] Show projected hardware pressure before activating a workflow.
- [ ] Provide hardware-aware presets such as **RTX 2070 Low VRAM**, **Balanced**, and **High VRAM**.
- [ ] Preserve a last-known-good workflow and provide one-click rollback.
- [ ] Support export/import as versioned JSON after validating model availability and typed connections.

## Test Bench integration

- [ ] Keep text translation, synthesized preview, round-trip verification, and diagnostics in Test Bench.
- [ ] Let Test Bench run against either the saved active workflow or an unsaved draft workflow.
- [ ] Clearly label which configuration produced each test result.
- [ ] Prevent test output caches from obscuring actual inference performance.

## Testing and acceptance criteria

- [ ] Add unit tests for schema validation, defaults, migrations, and unsafe-value rejection.
- [ ] Add API tests for read, validate, apply, rollback, reset, import, and export.
- [ ] Add UI tests for ellipsis-menu keyboard behavior and destructive-action separation.
- [ ] Add UI tests for dirty-state handling and failed adapter reload rollback.
- [ ] Add workflow graph tests for every allowed and forbidden connection type.
- [ ] Add benchmark tests proving warm-cache and cold-cache results are labeled separately.
- [ ] Verify the Higgs card no longer conflates 4.09 GB package size with runtime VRAM.
- [ ] Verify existing Live and Test Bench behavior remains functional.
- [ ] Update README screenshots and configuration documentation.
