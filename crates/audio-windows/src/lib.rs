//! VoxPassport Windows audio platform boundary.
//!
//! Endpoint discovery uses Windows Core Audio. Realtime microphone and system
//! loopback capture use bounded shared-mode/event-driven WASAPI streams.

mod capture;

use capture::{start_capture, CaptureKind};
use livetranslator_audio_core::{
    AudioCaptureConfig, AudioCaptureStream, AudioChunker, AudioEndpointDescriptor,
    AudioEndpointRole, AudioPlatform, AudioPlatformCapabilities, AudioPlatformError,
};
use livetranslator_protocol::{AudioBus, AudioFrame};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use windows::core::PWSTR;
use windows::Win32::Devices::FunctionDiscovery::PKEY_Device_FriendlyName;
use windows::Win32::Media::Audio::{
    eCapture, eConsole, eRender, EDataFlow, IMMDevice, IMMDeviceEnumerator,
    MMDeviceEnumerator, DEVICE_STATE_ACTIVE,
};
use windows::Win32::System::Com::StructuredStorage::{
    PropVariantClear, PropVariantToStringAlloc,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoTaskMemFree, CoUninitialize, CLSCTX_ALL,
    COINIT_MULTITHREADED, STGM_READ,
};

pub struct WindowsAudioPlatform;

impl WindowsAudioPlatform {
    pub fn new() -> Self {
        Self
    }

    /// Enumerate endpoints on a dedicated COM-initialized thread so callers do
    /// not need to own a particular COM apartment model.
    pub fn enumerate_endpoints_threaded(
        &self,
    ) -> Result<Vec<AudioEndpointDescriptor>, AudioPlatformError> {
        std::thread::spawn(enumerate_endpoints_mta)
            .join()
            .map_err(|_| AudioPlatformError::Platform("Windows endpoint enumeration thread panicked".into()))?
    }
}

impl Default for WindowsAudioPlatform {
    fn default() -> Self {
        Self::new()
    }
}

impl AudioPlatform for WindowsAudioPlatform {
    fn capabilities(&self) -> AudioPlatformCapabilities {
        AudioPlatformCapabilities {
            enumerate_microphones: true,
            capture_microphone: true,
            enumerate_render_endpoints: true,
            capture_loopback: true,
            virtual_microphone_output: false,
        }
    }

    fn enumerate_endpoints(&self) -> Result<Vec<AudioEndpointDescriptor>, AudioPlatformError> {
        self.enumerate_endpoints_threaded()
    }

    fn start_microphone_capture(
        &self,
        config: AudioCaptureConfig,
    ) -> Result<Box<dyn AudioCaptureStream>, AudioPlatformError> {
        start_capture(CaptureKind::Microphone, config)
    }

    fn start_loopback_capture(
        &self,
        config: AudioCaptureConfig,
    ) -> Result<Box<dyn AudioCaptureStream>, AudioPlatformError> {
        start_capture(CaptureKind::Loopback, config)
    }
}

fn enumerate_endpoints_mta() -> Result<Vec<AudioEndpointDescriptor>, AudioPlatformError> {
    unsafe {
        CoInitializeEx(None, COINIT_MULTITHREADED)
            .map_err(|error| AudioPlatformError::Platform(format!("CoInitializeEx failed: {error}")))?;
    }
    let result = enumerate_endpoints_initialized();
    unsafe { CoUninitialize() };
    result
}

fn enumerate_endpoints_initialized() -> Result<Vec<AudioEndpointDescriptor>, AudioPlatformError> {
    let enumerator: IMMDeviceEnumerator = unsafe {
        CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
            .map_err(|error| AudioPlatformError::Platform(format!("MMDeviceEnumerator creation failed: {error}")))?
    };

    let default_capture_id = default_endpoint_id(&enumerator, eCapture).ok();
    let default_render_id = default_endpoint_id(&enumerator, eRender).ok();

    let mut endpoints = Vec::new();
    endpoints.extend(enumerate_flow(
        &enumerator,
        eCapture,
        AudioEndpointRole::PhysicalMicrophone,
        default_capture_id.as_deref(),
    )?);

    let render = enumerate_flow(
        &enumerator,
        eRender,
        AudioEndpointRole::RenderOutput,
        default_render_id.as_deref(),
    )?;
    endpoints.extend(render.iter().cloned());
    // A render endpoint is also the stable identity used to request WASAPI
    // system-loopback capture. Keep the roles separate for routing/UI clarity.
    endpoints.extend(render.into_iter().map(|device| AudioEndpointDescriptor {
        id: device.id,
        name: format!("{} (system audio)", device.name),
        role: AudioEndpointRole::LoopbackSource,
        is_default: device.is_default,
    }));
    Ok(endpoints)
}

fn enumerate_flow(
    enumerator: &IMMDeviceEnumerator,
    flow: EDataFlow,
    role: AudioEndpointRole,
    default_id: Option<&str>,
) -> Result<Vec<AudioEndpointDescriptor>, AudioPlatformError> {
    let collection = unsafe {
        enumerator
            .EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
            .map_err(|error| AudioPlatformError::Platform(format!("EnumAudioEndpoints failed: {error}")))?
    };
    let count = unsafe {
        collection
            .GetCount()
            .map_err(|error| AudioPlatformError::Platform(format!("IMMDeviceCollection::GetCount failed: {error}")))?
    };

    let mut devices = Vec::with_capacity(count as usize);
    for index in 0..count {
        let device = unsafe {
            collection
                .Item(index)
                .map_err(|error| AudioPlatformError::Platform(format!("IMMDeviceCollection::Item({index}) failed: {error}")))?
        };
        let id = device_id(&device)?;
        let name = friendly_name(&device).unwrap_or_else(|_| id.clone());
        devices.push(AudioEndpointDescriptor {
            is_default: default_id == Some(id.as_str()),
            id,
            name,
            role,
        });
    }
    Ok(devices)
}

fn default_endpoint_id(
    enumerator: &IMMDeviceEnumerator,
    flow: EDataFlow,
) -> Result<String, AudioPlatformError> {
    let device = unsafe {
        enumerator
            .GetDefaultAudioEndpoint(flow, eConsole)
            .map_err(|error| AudioPlatformError::Platform(format!("GetDefaultAudioEndpoint failed: {error}")))?
    };
    device_id(&device)
}

fn device_id(device: &IMMDevice) -> Result<String, AudioPlatformError> {
    let id = unsafe {
        device
            .GetId()
            .map_err(|error| AudioPlatformError::Platform(format!("IMMDevice::GetId failed: {error}")))?
    };
    take_pwstr(id)
}

fn friendly_name(device: &IMMDevice) -> Result<String, AudioPlatformError> {
    let store = unsafe {
        device
            .OpenPropertyStore(STGM_READ)
            .map_err(|error| AudioPlatformError::Platform(format!("OpenPropertyStore failed: {error}")))?
    };
    let mut value = unsafe {
        store
            .GetValue(&PKEY_Device_FriendlyName)
            .map_err(|error| AudioPlatformError::Platform(format!("Friendly-name property lookup failed: {error}")))?
    };
    let text = unsafe {
        PropVariantToStringAlloc(&value)
            .map_err(|error| AudioPlatformError::Platform(format!("Friendly-name conversion failed: {error}")))?
    };
    let result = take_pwstr(text);
    unsafe {
        let _ = PropVariantClear(&mut value);
    }
    result
}

fn take_pwstr(value: PWSTR) -> Result<String, AudioPlatformError> {
    let result = unsafe {
        value
            .to_string()
            .map_err(|error| AudioPlatformError::Platform(format!("Windows UTF-16 conversion failed: {error}")))
    };
    unsafe { CoTaskMemFree(Some(value.0.cast())) };
    result
}

/// Compatibility metadata retained while callers migrate to AudioEndpointDescriptor.
pub struct WasapiAudioDevice {
    pub id: String,
    pub name: String,
    pub is_default: bool,
    pub is_loopback: bool,
}

/// In-memory PCM chunking utility retained for tests and non-device producers.
pub struct WasapiStreamSession {
    bus: AudioBus,
    is_running: Arc<AtomicBool>,
    chunker: AudioChunker,
}

impl WasapiStreamSession {
    pub fn new(bus: AudioBus, sample_rate_hz: u32, channels: u16) -> Self {
        Self {
            bus,
            is_running: Arc::new(AtomicBool::new(false)),
            chunker: AudioChunker::new(bus, sample_rate_hz, channels, 20),
        }
    }

    pub fn start(&mut self) {
        self.is_running.store(true, Ordering::SeqCst);
    }

    pub fn stop(&mut self) {
        self.is_running.store(false, Ordering::SeqCst);
    }

    pub fn is_active(&self) -> bool {
        self.is_running.load(Ordering::SeqCst)
    }

    pub fn bus(&self) -> AudioBus {
        self.bus
    }

    pub fn feed_pcm_data(&mut self, data: Vec<u8>) -> Option<AudioFrame> {
        if !self.is_active() {
            return None;
        }
        Some(self.chunker.process_raw_bytes(data))
    }
}
