use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct DesktopAudioCapabilities {
    pub platform: &'static str,
    pub native_audio_boundary: bool,
    pub microphone_enumeration: bool,
    pub microphone_capture: bool,
    pub render_enumeration: bool,
    pub loopback_capture: bool,
    pub virtual_microphone_output: bool,
    pub note: &'static str,
}

pub fn capabilities() -> DesktopAudioCapabilities {
    #[cfg(target_os = "windows")]
    {
        // A Windows-specific crate and portable audio contract exist, but the
        // current crate does not yet enumerate or open real WASAPI endpoints.
        // Keep every executable capability false until implementation/validation.
        return DesktopAudioCapabilities {
            platform: "windows",
            native_audio_boundary: true,
            microphone_enumeration: false,
            microphone_capture: false,
            render_enumeration: false,
            loopback_capture: false,
            virtual_microphone_output: false,
            note: "WASAPI endpoint enumeration/capture and virtual-mic output are not yet implemented",
        };
    }

    #[cfg(target_os = "macos")]
    {
        return DesktopAudioCapabilities {
            platform: "macos",
            native_audio_boundary: false,
            microphone_enumeration: false,
            microphone_capture: false,
            render_enumeration: false,
            loopback_capture: false,
            virtual_microphone_output: false,
            note: "CoreAudio backend not implemented",
        };
    }

    #[cfg(target_os = "linux")]
    {
        return DesktopAudioCapabilities {
            platform: "linux",
            native_audio_boundary: false,
            microphone_enumeration: false,
            microphone_capture: false,
            render_enumeration: false,
            loopback_capture: false,
            virtual_microphone_output: false,
            note: "PipeWire backend not implemented",
        };
    }

    #[allow(unreachable_code)]
    DesktopAudioCapabilities {
        platform: "unknown",
        native_audio_boundary: false,
        microphone_enumeration: false,
        microphone_capture: false,
        render_enumeration: false,
        loopback_capture: false,
        virtual_microphone_output: false,
        note: "unsupported desktop platform",
    }
}
