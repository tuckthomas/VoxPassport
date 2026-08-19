# Google Meet Integration — LiveTranslator

## Primary Integration: Virtual Microphone

The core audio integration does NOT depend on any Google Meet API.

1. The application routes translated Romanian TTS to an OS-level virtual audio device.
2. The user selects that virtual microphone in Google Meet's audio settings.
3. Remote participants hear translated Romanian as if it were a normal microphone.

This approach works identically for Zoom, Teams, Discord, Webex, and any other conferencing app.

## Setup Wizard Instructions

The setup wizard guides users through:

1. **Select your physical microphone** — used for English input capture
2. **Install a virtual audio cable** — VB-Cable (free) or equivalent
3. **In Google Meet:** Select the virtual cable as your microphone
4. **In Google Meet:** Keep your normal headphones/speakers for output
5. **In the companion app:** Select the conference output capture source

## Routing Verification

The app detects and warns about common routing errors:

| Problem | Warning |
|---------|---------|
| Physical mic selected in Meet (not virtual mic) | "Outbound translation is enabled but Meet is using your physical microphone. Remote participants will hear English, not Romanian." |
| Virtual mic feeding back into inbound capture | "The virtual microphone appears to be the selected loopback source. This will cause recursive translation." |

- Offer a test tone to verify virtual mic is received in Meet.
- Offer a test translated phrase before joining a meeting.
- Provide a device-routing diagram in the UI.

## Browser Extension (Optional, Future)

A Chrome Manifest V3 extension may be added for:
- Translated caption overlay within the Meet UI
- Language direction controls
- Mute/original-audio toggle
- Voice-clone enable/disable
- Pipeline status and latency indicator

**The extension is not required for audio translation.** Closing or uninstalling the extension does not affect translated audio.

The extension connects to the local companion via an authenticated local WebSocket (`127.0.0.1` only) using an ephemeral session token.

## Meet Add-ons SDK Evaluation

- **Status & Scope**: Provides side-panel and co-doing experiences within Google Meet Web client.
- **Limitation**: The SDK runs in an iframe inside the Meet client and cannot access raw multi-channel audio tracks or intercept microphone streams directly.
- **Architectural Decision**: Inference stays entirely on the local companion app. The Add-on is suitable only for displaying auxiliary transcriptions or status indicators, not audio processing.

## Meet Media API & OAuth Evaluation

- **Status**: Google Meet Media API operates via WebRTC signaling servers. It allows external applications to join a meeting as a bot/endpoint and receive individual participant audio/video RTP streams.
- **Authentication & OAuth**:
  - Requires Google Cloud Project with Meet Media API enabled.
  - Requires Google Workspace Enterprise administrator authorization and sensitive OAuth scopes (`https://www.googleapis.com/auth/meetings.space.readonly`, `https://www.googleapis.com/auth/meetings.space.created`).
  - Requires a publicly reachable WebRTC endpoint to negotiate ICE/STUN/TURN candidates and receive encrypted RTP streams.
- **End-User Practicality**:
  - Unpractical for consumer/standalone end users who want a one-click local translator without setting up Google Cloud developer accounts or Workspace domain-wide delegation.
  - Adds cloud infrastructure cost and latency (transmitting RTP to a relay server vs local loopback).
- **Architectural Conclusion (§37)**:
  - **OS Loopback Capture via WASAPI (Windows) / CoreAudio (macOS) / PipeWire (Linux)** is vastly superior in privacy, zero-setup friction, zero cloud costs, and instant local-first reliability.
  - The generic conference mode (virtual microphone + OS loopback capture) is the permanent production foundation. Clean per-participant Media API ingestion is preserved as an optional enterprise add-on path only.

