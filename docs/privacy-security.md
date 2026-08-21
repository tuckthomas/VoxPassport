# Privacy & Security — LiveTranslator

## Data Processing Principles

1. **Local-first inference.** All AI processing runs on-device by default.
2. **No transcript persistence.** Transcripts, translations, and source text are never written to disk by default.
3. **No unattended audio recording.** Live audio is processed in memory and is
   not saved automatically. Voice Profile Studio explicitly records and saves
   a reference sample when the user starts enrollment, and users may also save
   or import audio for a requested voice-cloning workflow.
4. **Content-free metrics.** All performance metrics contain only numeric values — no speech content.
5. **Explicit consent for voice cloning.** Voice enrollment requires explicit user action.

## Default Privacy Settings

| Setting | Default | Notes |
|---------|---------|-------|
| `persist_transcripts` | `false` | Transcripts stay in memory only |
| `persist_audio` | `false` | Live audio is not written automatically; explicit voice-profile enrollment or user-requested audio saves are exceptions |
| `persist_translation_history` | `false` | Translations not logged |
| `voice_cloning_enabled` | `false` | Must be explicitly enabled |
| `remote_inference` | `false` | All inference local by default |
| `remote_audio_transmission` | `false` | Opt-in only, with clear disclosure |

## Voice Cloning Safety

- Voice enrollment is initiated only by the user through an explicit UI action.
- Only the user's own voice may be enrolled (not remote participants).
- The application displays which enrolled voice profile is currently active.
- One-click deletion of enrolled voice profiles is always available.
- Persisted speaker conditioning data is encrypted at rest.
- The application shows a visible indicator whenever synthetic speech is active.
- The application never creates a "clone this meeting participant" automatic feature.

## Remote Inference (When Enabled)

- All remote inference traffic is TLS-encrypted.
- Desktop client is authenticated to the inference server.
- Raw audio transmission to a remote server requires explicit opt-in.
- Data retention on the remote server is configured explicitly.
- Audio is not persisted remotely by default.
- Network latency is monitored continuously; user is warned when latency makes real-time use impractical.

## Local IPC Security

- Local WebSocket for browser extension binds to `127.0.0.1` only.
- An ephemeral session token is generated at startup.
- Every extension connection is authenticated with the session token.
- Allowed origins are validated and strictly limited.
- Model-management endpoints are not exposed to the browser extension.

## Logs and Diagnostics

- Standard logs contain no spoken content, transcripts, or translations.
- Diagnostic reports exported by the user contain only numeric/status data.
- Hot-swap failures are recorded in content-free diagnostic logs.
- Speaker voice profiles are not included in diagnostic exports.

## Trust and Code Execution

- Models requiring `trust_remote_code=True` are flagged, displayed clearly, and require explicit approval.
- Sandboxed execution is preferred for models requiring custom code.
- Unverified catalog entries cannot silently replace official installed models.
- Adapter plugins must be signed/approved (when the plugin system matures).
