use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct DesktopAudioCapabilities {
    pub platform: &'static str,
    pub native_audio: bool,
    pub physical_microphone: bool,
    pub loopback_capture: bool,
    pub virtual_microphone_output: bool,
    pub virtual_microphone_note: &'static str,
}

pub fn capabilities() -> DesktopAudioCapabilities {
    #[cfg(target_os = "windows")]
    {
        // The existing Windows audio crate provides the native WASAPI boundary.
        // A real installed/selectable virtual microphone endpoint is deliberately
        // reported false until its driver/output path is implemented and validated.
        return DesktopAudioCapabilities {
            platform: "windows",
            native_audio: true,
            physical_microphone: true,
            loopback_capture: true,
            virtual_microphone_output: false,
            virtual_microphone_note: "virtual microphone endpoint not yet validated",
        };
    }

    #[cfg(target_os = "macos")]
    {
        return DesktopAudioCapabilities {
            platform: "macos",
            native_audio: false,
            physical_microphone: false,
            loopback_capture: false,
            virtual_microphone_output: false,
            virtual_microphone_note: "CoreAudio backend not implemented",
        };
    }

    #[cfg(target_os = "linux")]
    {
        return DesktopAudioCapabilities {
            platform: "linux",
            native_audio: false,
            physical_microphone: false,
            loopback_capture: false,
            virtual_microphone_output: false,
            virtual_microphone_note: "PipeWire backend not implemented",
        };
    }

    #[allow(unreachable_code)]
    DesktopAudioCapabilities {
        platform: "unknown",
        native_audio: false,
        physical_microphone: false,
        loopback_capture: false,
        virtual_microphone_output: false,
        virtual_microphone_note: "unsupported desktop platform",
    }
}
