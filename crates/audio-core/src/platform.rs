use livetranslator_protocol::AudioFrame;
use std::time::Duration;
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AudioCaptureConfig {
    /// Stable OS endpoint ID. None selects the current Windows default endpoint.
    pub endpoint_id: Option<String>,
    pub sample_rate_hz: u32,
    pub channels: u16,
    pub chunk_duration_ms: u32,
    /// Bounded frame queue. Producers drop newest frames rather than allowing unbounded latency growth.
    pub queue_capacity: usize,
}

impl Default for AudioCaptureConfig {
    fn default() -> Self {
        Self {
            endpoint_id: None,
            sample_rate_hz: 16_000,
            channels: 1,
            chunk_duration_ms: 20,
            queue_capacity: 8,
        }
    }
}

impl AudioCaptureConfig {
    pub fn validate(&self) -> Result<(), AudioPlatformError> {
        if self.sample_rate_hz == 0 {
            return Err(AudioPlatformError::InvalidConfiguration("sample_rate_hz must be positive".into()));
        }
        if self.channels == 0 {
            return Err(AudioPlatformError::InvalidConfiguration("channels must be positive".into()));
        }
        if self.chunk_duration_ms == 0 || self.chunk_duration_ms > 1_000 {
            return Err(AudioPlatformError::InvalidConfiguration(
                "chunk_duration_ms must be between 1 and 1000".into(),
            ));
        }
        if self.queue_capacity == 0 || self.queue_capacity > 512 {
            return Err(AudioPlatformError::InvalidConfiguration(
                "queue_capacity must be between 1 and 512".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct AudioCaptureStats {
    pub frames_emitted: u64,
    pub frames_dropped: u64,
}

#[derive(Debug, Error)]
pub enum AudioPlatformError {
    #[error("audio platform is not supported: {0}")]
    Unsupported(String),
    #[error("invalid audio configuration: {0}")]
    InvalidConfiguration(String),
    #[error("audio platform operation failed: {0}")]
    Platform(String),
}

/// One running native capture stream. The queue is bounded by AudioCaptureConfig.
pub trait AudioCaptureStream: Send {
    /// Return the next PCM frame, None on timeout.
    fn recv_timeout(&self, timeout: Duration) -> Result<Option<AudioFrame>, AudioPlatformError>;
    fn stop(&mut self);
    fn is_active(&self) -> bool;
    fn stats(&self) -> AudioCaptureStats;
}

/// Native desktop audio boundary.
///
/// Realtime PCM stays behind this interface. UI code should receive only device
/// metadata, levels, state, and other low-frequency events. The Python runtime
/// or another media-plane owner consumes AudioCaptureStream directly.
pub trait AudioPlatform: Send + Sync {
    fn capabilities(&self) -> AudioPlatformCapabilities;
    fn enumerate_endpoints(&self) -> Result<Vec<AudioEndpointDescriptor>, AudioPlatformError>;

    fn start_microphone_capture(
        &self,
        _config: AudioCaptureConfig,
    ) -> Result<Box<dyn AudioCaptureStream>, AudioPlatformError> {
        Err(AudioPlatformError::Unsupported("microphone capture is not implemented".into()))
    }

    fn start_loopback_capture(
        &self,
        _config: AudioCaptureConfig,
    ) -> Result<Box<dyn AudioCaptureStream>, AudioPlatformError> {
        Err(AudioPlatformError::Unsupported("loopback capture is not implemented".into()))
    }
}
