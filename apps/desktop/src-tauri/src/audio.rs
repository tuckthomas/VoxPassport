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

#[derive(Debug, Clone, Serialize)]
pub struct DesktopAudioDevice {
    pub id: String,
    pub name: String,
    pub role: &'static str,
    pub is_default: bool,
}

pub fn capabilities() -> DesktopAudioCapabilities {
    #[cfg(target_os = "windows")]
    {
        return DesktopAudioCapabilities {
            platform: "windows",
            native_audio_boundary: true,
            microphone_enumeration: true,
            microphone_capture: false,
            render_enumeration: true,
            loopback_capture: false,
            virtual_microphone_output: false,
            note: "WASAPI endpoint enumeration implemented; executable/hardware validation and realtime capture/output remain pending",
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

pub fn devices() -> Result<Vec<DesktopAudioDevice>, String> {
    #[cfg(target_os = "windows")]
    {
        use livetranslator_audio_core::{AudioEndpointRole, AudioPlatform};
        use livetranslator_audio_windows::WindowsAudioPlatform;

        return WindowsAudioPlatform::new()
            .enumerate_endpoints()
            .map(|devices| {
                devices
                    .into_iter()
                    .map(|device| DesktopAudioDevice {
                        id: device.id,
                        name: device.name,
                        role: match device.role {
                            AudioEndpointRole::PhysicalMicrophone => "physical_microphone",
                            AudioEndpointRole::RenderOutput => "render_output",
                            AudioEndpointRole::LoopbackSource => "loopback_source",
                            AudioEndpointRole::VirtualMicrophoneSink => "virtual_microphone_sink",
                        },
                        is_default: device.is_default,
                    })
                    .collect()
            })
            .map_err(|error| error.to_string());
    }

    #[cfg(not(target_os = "windows"))]
    {
        Err("native audio endpoint enumeration is not implemented on this platform".to_string())
    }
}
