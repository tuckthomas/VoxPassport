use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AudioEndpointRole {
    PhysicalMicrophone,
    RenderOutput,
    LoopbackSource,
    VirtualMicrophoneSink,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AudioEndpointDescriptor {
    /// Stable operating-system endpoint identifier. UI code must not persist a display name as identity.
    pub id: String,
    pub name: String,
    pub role: AudioEndpointRole,
    pub is_default: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AudioPlatformCapabilities {
    pub enumerate_microphones: bool,
    pub capture_microphone: bool,
    pub enumerate_render_endpoints: bool,
    pub capture_loopback: bool,
    pub virtual_microphone_output: bool,
}

#[derive(Debug, Error)]
pub enum AudioPlatformError {
    #[error("audio platform is not supported: {0}")]
    Unsupported(String),
    #[error("audio platform operation failed: {0}")]
    Platform(String),
}

/// Native desktop audio boundary.
///
/// Realtime PCM stays behind this interface. UI/native-shell IPC should receive
/// only device metadata, levels, state, and other low-frequency events.
pub trait AudioPlatform: Send + Sync {
    fn capabilities(&self) -> AudioPlatformCapabilities;
    fn enumerate_endpoints(&self) -> Result<Vec<AudioEndpointDescriptor>, AudioPlatformError>;
}
