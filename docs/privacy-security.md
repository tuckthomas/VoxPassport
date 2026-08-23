# VoxPassport Privacy & Security

## Data processing principles

1. **Local-first inference.** The reference pipeline runs on-device by default.
2. **No transcript persistence by default.** Live transcripts, translations, and source text are not written to disk unless a user-requested workflow explicitly saves them.
3. **No unattended audio recording.** Live audio is processed in memory and is not saved automatically. Voice Profile Studio explicitly records/saves a reference when the user starts enrollment, and users may intentionally import or export audio.
4. **Content-free metrics.** Performance metrics should contain numeric/status data rather than spoken content.
5. **Explicit voice-profile enrollment.** Creating a reusable voice identity requires an explicit user action.
6. **Remote inference is opt-in.** Local worker processes are not considered remote inference merely because they communicate over localhost HTTP.

## Default privacy settings

| Setting | Default | Notes |
| --- | --- | --- |
| `persist_transcripts` | `false` | Live transcripts stay in memory unless explicitly saved |
| `persist_audio` | `false` | Live audio is not written automatically; voice-profile enrollment/export is an explicit exception |
| `persist_translation_history` | `false` | Translation history is not logged by default |
| `voice_cloning_enabled` | `false` | Must be explicitly enabled |
| `remote_inference` | `false` | Reference pipeline remains local |
| `remote_audio_transmission` | `false` | Opt-in only |

## Voice profiles

A canonical local voice profile may contain:

```text
reference.wav
reference.txt        # optional unless a selected model requires it
profile metadata
conditioning/...     # optional derived model-conditioning assets
```

The reference recording is the canonical speaker identity. A transcript is not globally mandatory; the selected TTS manifest declares whether its driver requires one.

Derived target-language conditioning must not overwrite the canonical reference recording.

## Voice cloning safety

- Voice enrollment is initiated only through an explicit user action.
- The application displays which saved voice profile is active.
- One-click deletion of voice profiles should remain available.
- Synthetic-speech state should be visible to the user.
- Remote-participant cloning should not occur automatically merely because diarization detects a different speaker.

## Local TTS worker processes

Local manifest-driven TTS uses:

```text
ManifestTtsAdapter
    -> localhost voxpassport.tts.v1
    -> generic worker host
    -> TtsDriver
```

A worker may run under a separate Python environment such as `.venv-xtts`. That isolation exists for dependency/fault boundaries; it does **not** make the model a remote service.

Security rules for local TTS workers:

- bind to loopback only;
- do not expose worker ports to the LAN/WAN;
- accept local file paths only from the trusted VoxPassport process/workflow;
- avoid writing generated speech or transcripts unless the user explicitly requests persistence;
- keep worker diagnostics content-free where practical;
- terminate or unload workers cleanly so voice/model state is not retained unnecessarily.

The current fixed `:8098` / `:8099` topology should eventually be replaced by supervisor-managed runtime profiles. Dynamically assigned local endpoints should still bind only to loopback.

## Remote inference

Remote inference is a separate feature from local TTS workers.

When remote inference is enabled:

- use TLS for off-device traffic;
- authenticate the client/worker;
- require explicit opt-in before raw audio or voice-profile material leaves the machine;
- make remote retention policy explicit;
- avoid remote persistence by default;
- monitor network latency and health;
- do not assume a remote TTS worker can access local voice-profile paths without an explicit secure synchronization/enrollment design.

See `docs/remote-workers.md`.

## Local IPC security

- Local browser/caption services bind to `127.0.0.1`.
- Local TTS worker hosts also bind to loopback.
- Browser-extension connections should use startup/session authentication as implemented by the client/server integration.
- Browser-facing code should not gain direct access to model-management or arbitrary local-file worker endpoints.

## Logs and diagnostics

- Standard logs should avoid spoken content, transcripts, and translations.
- Diagnostic exports should contain numeric/status/model/runtime data rather than conversation content.
- Hot-swap and worker failures may log model IDs, runtime profile IDs, ports, process state, and error classes without logging speech text.
- Voice-reference audio must not be included in diagnostic exports automatically.

## Trust and code execution

Local TTS manifests are declarations, not permission to execute arbitrary untrusted code silently.

- Driver entrypoints included with VoxPassport should be reviewed repository code.
- Models requiring `trust_remote_code=True` should remain clearly flagged and require explicit approval.
- Unverified catalog entries must not silently replace validated installed models.
- A future runtime-profile supervisor should treat environment provisioning and driver execution as a trust boundary and should not install arbitrary dependency sets without an explicit model/runtime-profile installation action.
