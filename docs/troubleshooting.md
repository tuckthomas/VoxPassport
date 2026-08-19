# Troubleshooting — LiveTranslator

## Audio Routing Issues

### No sound through virtual microphone
1. Verify the virtual audio cable driver is installed (VB-Cable or equivalent).
2. Open the diagnostics panel — check "Virtual mic output meter."
3. Ensure the TTS pipeline is active (check TTS status indicator).
4. In Google Meet, confirm the virtual cable device is selected as the microphone.

### Feedback / Echo
1. Use headphones rather than speakers during full-duplex sessions.
2. Verify "Inbound TTS" is not routed to a device that is also captured as conference audio.
3. Check the audio routing diagram in the UI for incorrect bus connections.

### Recursive translation loop
1. The app displays a "RECURSION_SUSPECTED" alert if it detects repeated identical transcript sequences.
2. Check that the inbound capture source does not include the local speaker/TTS output device.
3. Verify AEC is enabled.

## Model Errors

### GPU Out of Memory
- The application catches OOM errors, flushes safely, and attempts to fall back to a lower-memory model or mode.
- Check the configured fallback chain in Model Settings.
- Consider switching to a smaller quantization (int8) or lower-tier model.

### ASR producing nonsense / wrong language
- Verify the correct ASR model is active for each direction (ASR EN vs. ASR RO).
- Check that the physical mic capture source is actually capturing speech (input meter).
- Re-run the ASR bakeoff against a known audio sample.

### Translation quality poor
- Check the active MT model and quantization.
- Try switching to the 4B MT model if the 1B is active.
- Ensure conversational context is being passed correctly (check `TranslationContext`).

### TTS audio artifacts at chunk boundaries
- Check TTS chunk size configuration.
- Verify PCM resampler settings (no repeated resampling).
- File an issue with the specific TTS model and version.

## Model Hot-Swap Issues

### Hot-swap stuck in PRELOADING
- Check VRAM availability — insufficient VRAM prevents simultaneous model residency.
- The app will pause, drain, unload old model, then load new model sequentially.
- If this fails, the app rolls back to the previous known-good model automatically.

### Model fails health check after swap
- The app automatically restores the prior known-good model.
- Check the content-free diagnostic log for error codes.
- Verify the new model is fully downloaded (checksum validation).

## Installation Issues

### Model download fails
- Check network connectivity.
- Downloads use resumable transfers — retry should continue from where it stopped.
- Verify disk space at the configured model storage path.
- Failed/incomplete downloads are cleaned up automatically.

## Session Stability

### Memory grows over a long session
- The app should not grow unboundedly — report as a bug.
- Collect a content-free diagnostic report and the metrics log.
- Check queue depths in the diagnostics panel for any unbounded accumulation.

## Exporting a Diagnostic Report

1. Open the Diagnostics panel.
2. Click "Export content-free diagnostic report."
3. The report contains only numeric metrics, status codes, model IDs, and hardware info — no spoken content.
