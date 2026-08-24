//! VoxPassport Linux native-audio backend.
//!
//! PipeWire owns realtime device I/O. We intentionally invoke its native
//! `pw-record` / `pw-play` clients for raw PCM instead of routing media through
//! PulseAudio JSON or the UI. PipeWire-Pulse (`pactl`) is used only for stable
//! endpoint discovery and for the separately installed virtual sink/source.

use livetranslator_audio_core::{
    AudioCaptureConfig, AudioCaptureStats, AudioCaptureStream, AudioEndpointDescriptor,
    AudioEndpointRole, AudioPlatform, AudioPlatformCapabilities, AudioPlatformError,
    AudioRenderConfig, AudioRenderStats, AudioRenderStream,
};
use livetranslator_protocol::{AudioFrame, SampleFormat};
use serde_json::Value;
use std::io::{Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub const VOXPASSPORT_VIRTUAL_RENDER_ID: &str = "voxpassport_translation_sink";
pub const VOXPASSPORT_VIRTUAL_CAPTURE_ID: &str = "voxpassport_virtual_microphone";
pub const VOXPASSPORT_VIRTUAL_RENDER_NAME: &str = "VoxPassport Translation Sink";
pub const VOXPASSPORT_VIRTUAL_CAPTURE_NAME: &str = "VoxPassport Virtual Microphone";

#[derive(Debug, Clone)]
struct SinkInfo {
    id: String,
    description: String,
    monitor_source: String,
}

pub struct LinuxAudioPlatform;

impl LinuxAudioPlatform {
    pub fn new() -> Self {
        Self
    }

    pub fn has_voxpassport_virtual_microphone(
        endpoints: &[AudioEndpointDescriptor],
    ) -> bool {
        let render = endpoints.iter().any(|item| {
            item.role == AudioEndpointRole::RenderOutput
                && (item.id == VOXPASSPORT_VIRTUAL_RENDER_ID
                    || item.name.eq_ignore_ascii_case(VOXPASSPORT_VIRTUAL_RENDER_NAME))
        });
        let capture = endpoints.iter().any(|item| {
            item.role == AudioEndpointRole::PhysicalMicrophone
                && (item.id == VOXPASSPORT_VIRTUAL_CAPTURE_ID
                    || item.name.eq_ignore_ascii_case(VOXPASSPORT_VIRTUAL_CAPTURE_NAME))
        });
        render && capture
    }

    fn default_source() -> Result<String, AudioPlatformError> {
        pactl_text(&["get-default-source"])
    }

    fn default_sink() -> Result<String, AudioPlatformError> {
        pactl_text(&["get-default-sink"])
    }

    fn sinks() -> Result<Vec<SinkInfo>, AudioPlatformError> {
        let value = pactl_json(&["list", "sinks"])?;
        let entries = value.as_array().ok_or_else(|| {
            AudioPlatformError::Platform("pactl sinks response was not a JSON array".into())
        })?;
        entries
            .iter()
            .map(|entry| {
                let id = json_string(entry, "name")?;
                let description = entry
                    .get("description")
                    .and_then(Value::as_str)
                    .unwrap_or(&id)
                    .to_owned();
                let monitor_source = entry
                    .get("monitor_source")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
                    .unwrap_or_else(|| format!("{id}.monitor"));
                Ok(SinkInfo {
                    id,
                    description,
                    monitor_source,
                })
            })
            .collect()
    }

    fn resolve_loopback_target(endpoint_id: Option<&str>) -> Result<String, AudioPlatformError> {
        if let Some(id) = endpoint_id {
            return Ok(id.to_owned());
        }
        let default_sink = Self::default_sink()?;
        Self::sinks()?
            .into_iter()
            .find(|sink| sink.id == default_sink)
            .map(|sink| sink.monitor_source)
            .ok_or_else(|| {
                AudioPlatformError::Platform(format!(
                    "default PipeWire sink {default_sink:?} has no monitor source"
                ))
            })
    }
}

impl Default for LinuxAudioPlatform {
    fn default() -> Self {
        Self::new()
    }
}

impl AudioPlatform for LinuxAudioPlatform {
    fn capabilities(&self) -> AudioPlatformCapabilities {
        AudioPlatformCapabilities {
            enumerate_microphones: command_exists("pactl"),
            capture_microphone: command_exists("pw-record"),
            enumerate_render_endpoints: command_exists("pactl"),
            capture_loopback: command_exists("pw-record"),
            render_output: command_exists("pw-play"),
            // The helper probe promotes this dynamically only when both
            // VoxPassport virtual endpoints actually enumerate.
            virtual_microphone_output: false,
        }
    }

    fn enumerate_endpoints(&self) -> Result<Vec<AudioEndpointDescriptor>, AudioPlatformError> {
        let default_sink = Self::default_sink().ok();
        let default_source = Self::default_source().ok();
        let sinks = Self::sinks()?;
        let source_json = pactl_json(&["list", "sources"])?;
        let sources = source_json.as_array().ok_or_else(|| {
            AudioPlatformError::Platform("pactl sources response was not a JSON array".into())
        })?;

        let mut endpoints = Vec::new();
        for sink in &sinks {
            let is_default = default_sink.as_deref() == Some(sink.id.as_str());
            endpoints.push(AudioEndpointDescriptor {
                id: sink.id.clone(),
                name: sink.description.clone(),
                role: AudioEndpointRole::RenderOutput,
                is_default,
            });
            endpoints.push(AudioEndpointDescriptor {
                id: sink.monitor_source.clone(),
                name: format!("{} (system audio)", sink.description),
                role: AudioEndpointRole::LoopbackSource,
                is_default,
            });
        }

        for source in sources {
            let id = json_string(source, "name")?;
            // PulseAudio uses PA_INVALID_INDEX (u32::MAX) for a normal source,
            // so merely checking monitor_of_sink for non-null incorrectly
            // classifies physical microphones as monitors. A real monitor has
            // an owning-sink name; the conventional .monitor suffix is retained
            // as a compatibility fallback for PipeWire-Pulse variants.
            if source_is_monitor(source, &id) {
                continue;
            }
            let name = source
                .get("description")
                .and_then(Value::as_str)
                .unwrap_or(&id)
                .to_owned();
            endpoints.push(AudioEndpointDescriptor {
                is_default: default_source.as_deref() == Some(id.as_str()),
                id,
                name,
                role: AudioEndpointRole::PhysicalMicrophone,
            });
        }
        Ok(endpoints)
    }

    fn start_microphone_capture(
        &self,
        config: AudioCaptureConfig,
    ) -> Result<Box<dyn AudioCaptureStream>, AudioPlatformError> {
        config.validate()?;
        let target = match config.endpoint_id.as_deref() {
            Some(id) => id.to_owned(),
            None => Self::default_source()?,
        };
        Ok(Box::new(PipeWireCapture::start(target, config)?))
    }

    fn start_loopback_capture(
        &self,
        config: AudioCaptureConfig,
    ) -> Result<Box<dyn AudioCaptureStream>, AudioPlatformError> {
        config.validate()?;
        let target = Self::resolve_loopback_target(config.endpoint_id.as_deref())?;
        Ok(Box::new(PipeWireCapture::start(target, config)?))
    }

    fn start_render_output(
        &self,
        config: AudioRenderConfig,
    ) -> Result<Box<dyn AudioRenderStream>, AudioPlatformError> {
        config.validate()?;
        let target = match config.endpoint_id.as_deref() {
            Some(id) => id.to_owned(),
            None => Self::default_sink()?,
        };
        Ok(Box::new(PipeWireRender::start(target, config)?))
    }
}

fn source_is_monitor(source: &Value, id: &str) -> bool {
    if id.ends_with(".monitor") {
        return true;
    }
    if source
        .get("monitor_of_sink_name")
        .and_then(Value::as_str)
        .is_some_and(|name| !name.is_empty())
    {
        return true;
    }
    source
        .get("properties")
        .and_then(Value::as_object)
        .and_then(|properties| properties.get("device.class"))
        .and_then(Value::as_str)
        .is_some_and(|class| class.eq_ignore_ascii_case("monitor"))
}

fn json_string(value: &Value, key: &str) -> Result<String, AudioPlatformError> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| AudioPlatformError::Platform(format!("pactl entry is missing string field {key:?}")))
}

fn pactl_json(args: &[&str]) -> Result<Value, AudioPlatformError> {
    let mut command = Command::new("pactl");
    command.arg("-f").arg("json").args(args);
    let output = command.output().map_err(|error| {
        AudioPlatformError::Platform(format!("failed to launch pactl: {error}"))
    })?;
    if !output.status.success() {
        return Err(AudioPlatformError::Platform(format!(
            "pactl {} failed: {}",
            args.join(" "),
            String::from_utf8_lossy(&output.stderr).trim()
        )));
    }
    serde_json::from_slice(&output.stdout).map_err(|error| {
        AudioPlatformError::Platform(format!("pactl returned invalid JSON: {error}"))
    })
}

fn pactl_text(args: &[&str]) -> Result<String, AudioPlatformError> {
    let output = Command::new("pactl").args(args).output().map_err(|error| {
        AudioPlatformError::Platform(format!("failed to launch pactl: {error}"))
    })?;
    if !output.status.success() {
        return Err(AudioPlatformError::Platform(format!(
            "pactl {} failed: {}",
            args.join(" "),
            String::from_utf8_lossy(&output.stderr).trim()
        )));
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    if value.is_empty() {
        return Err(AudioPlatformError::Platform(format!(
            "pactl {} returned an empty endpoint name",
            args.join(" ")
        )));
    }
    Ok(value)
}

fn command_exists(command: &str) -> bool {
    Command::new(command)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

struct PipeWireCapture {
    receiver: Receiver<AudioFrame>,
    active: Arc<AtomicBool>,
    emitted: Arc<AtomicU64>,
    dropped: Arc<AtomicU64>,
    child: Arc<Mutex<Child>>,
    worker: Option<JoinHandle<()>>,
}

impl PipeWireCapture {
    fn start(target: String, config: AudioCaptureConfig) -> Result<Self, AudioPlatformError> {
        let mut child = Command::new("pw-record")
            .arg("--raw")
            .arg("--rate")
            .arg(config.sample_rate_hz.to_string())
            .arg("--channels")
            .arg(config.channels.to_string())
            .arg("--format")
            .arg("s16")
            .arg("--latency")
            .arg(format!("{}ms", config.chunk_duration_ms))
            .arg("--target")
            .arg(&target)
            .arg("-")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| AudioPlatformError::Platform(format!("failed to launch pw-record: {error}")))?;
        let mut stdout = child.stdout.take().ok_or_else(|| {
            AudioPlatformError::Platform("pw-record stdout pipe is unavailable".into())
        })?;
        let child = Arc::new(Mutex::new(child));
        let active = Arc::new(AtomicBool::new(true));
        let emitted = Arc::new(AtomicU64::new(0));
        let dropped = Arc::new(AtomicU64::new(0));
        let (sender, receiver) = mpsc::sync_channel(config.queue_capacity);
        let worker_active = Arc::clone(&active);
        let worker_emitted = Arc::clone(&emitted);
        let worker_dropped = Arc::clone(&dropped);
        let bytes_per_chunk = ((config.sample_rate_hz as u64
            * config.channels as u64
            * 2
            * config.chunk_duration_ms as u64)
            / 1000) as usize;
        let stream_id = format!("pipewire:{target}");
        let sample_rate_hz = config.sample_rate_hz;
        let channels = config.channels;
        let worker = thread::spawn(move || {
            let mut sequence = 0u64;
            let mut data = vec![0u8; bytes_per_chunk.max(2)];
            while worker_active.load(Ordering::Acquire) {
                if stdout.read_exact(&mut data).is_err() {
                    break;
                }
                let frame = AudioFrame {
                    stream_id: stream_id.clone(),
                    sequence,
                    monotonic_timestamp_ns: timestamp_ns(),
                    sample_rate_hz,
                    channels,
                    sample_format: SampleFormat::PcmS16le,
                    data: data.clone(),
                };
                sequence = sequence.wrapping_add(1);
                match sender.try_send(frame) {
                    Ok(()) => {
                        worker_emitted.fetch_add(1, Ordering::Relaxed);
                    }
                    Err(TrySendError::Full(_)) => {
                        worker_dropped.fetch_add(1, Ordering::Relaxed);
                    }
                    Err(TrySendError::Disconnected(_)) => break,
                }
            }
            worker_active.store(false, Ordering::Release);
        });
        Ok(Self {
            receiver,
            active,
            emitted,
            dropped,
            child,
            worker: Some(worker),
        })
    }
}

impl AudioCaptureStream for PipeWireCapture {
    fn recv_timeout(&self, timeout: Duration) -> Result<Option<AudioFrame>, AudioPlatformError> {
        match self.receiver.recv_timeout(timeout) {
            Ok(frame) => Ok(Some(frame)),
            Err(mpsc::RecvTimeoutError::Timeout) => Ok(None),
            Err(mpsc::RecvTimeoutError::Disconnected) => Ok(None),
        }
    }

    fn stop(&mut self) {
        if !self.active.swap(false, Ordering::AcqRel) {
            return;
        }
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }

    fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }

    fn stats(&self) -> AudioCaptureStats {
        AudioCaptureStats {
            frames_emitted: self.emitted.load(Ordering::Relaxed),
            frames_dropped: self.dropped.load(Ordering::Relaxed),
        }
    }
}

impl Drop for PipeWireCapture {
    fn drop(&mut self) {
        self.stop();
    }
}

struct PipeWireRender {
    sender: Option<SyncSender<AudioFrame>>,
    active: Arc<AtomicBool>,
    accepted: Arc<AtomicU64>,
    dropped: Arc<AtomicU64>,
    child: Arc<Mutex<Child>>,
    worker: Option<JoinHandle<()>>,
    sample_rate_hz: u32,
    channels: u16,
}

impl PipeWireRender {
    fn start(target: String, config: AudioRenderConfig) -> Result<Self, AudioPlatformError> {
        let mut child = Command::new("pw-play")
            .arg("--raw")
            .arg("--rate")
            .arg(config.sample_rate_hz.to_string())
            .arg("--channels")
            .arg(config.channels.to_string())
            .arg("--format")
            .arg("s16")
            .arg("--target")
            .arg(&target)
            .arg("-")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| AudioPlatformError::Platform(format!("failed to launch pw-play: {error}")))?;
        let mut stdin = child.stdin.take().ok_or_else(|| {
            AudioPlatformError::Platform("pw-play stdin pipe is unavailable".into())
        })?;
        let child = Arc::new(Mutex::new(child));
        let active = Arc::new(AtomicBool::new(true));
        let accepted = Arc::new(AtomicU64::new(0));
        let dropped = Arc::new(AtomicU64::new(0));
        let (sender, receiver) = mpsc::sync_channel::<AudioFrame>(config.queue_capacity);
        let worker_active = Arc::clone(&active);
        let worker = thread::spawn(move || {
            while worker_active.load(Ordering::Acquire) {
                match receiver.recv_timeout(Duration::from_millis(100)) {
                    Ok(frame) => {
                        if stdin.write_all(&frame.data).is_err() {
                            break;
                        }
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => continue,
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }
            let _ = stdin.flush();
            worker_active.store(false, Ordering::Release);
        });
        Ok(Self {
            sender: Some(sender),
            active,
            accepted,
            dropped,
            child,
            worker: Some(worker),
            sample_rate_hz: config.sample_rate_hz,
            channels: config.channels,
        })
    }
}

impl AudioRenderStream for PipeWireRender {
    fn try_write(&self, frame: AudioFrame) -> Result<bool, AudioPlatformError> {
        if !self.is_active() {
            return Err(AudioPlatformError::Platform("PipeWire render stream is stopped".into()));
        }
        if frame.sample_rate_hz != self.sample_rate_hz || frame.channels != self.channels {
            return Err(AudioPlatformError::InvalidConfiguration(format!(
                "PipeWire render expects {} Hz / {} channel(s)",
                self.sample_rate_hz, self.channels
            )));
        }
        if frame.sample_format != SampleFormat::PcmS16le {
            return Err(AudioPlatformError::InvalidConfiguration(
                "PipeWire helper render currently requires pcm_s16le".into(),
            ));
        }
        let sender = self.sender.as_ref().ok_or_else(|| {
            AudioPlatformError::Platform("PipeWire render queue is closed".into())
        })?;
        match sender.try_send(frame) {
            Ok(()) => {
                self.accepted.fetch_add(1, Ordering::Relaxed);
                Ok(true)
            }
            Err(TrySendError::Full(_)) => {
                self.dropped.fetch_add(1, Ordering::Relaxed);
                Ok(false)
            }
            Err(TrySendError::Disconnected(_)) => Err(AudioPlatformError::Platform(
                "PipeWire render worker disconnected".into(),
            )),
        }
    }

    fn stop(&mut self) {
        if !self.active.swap(false, Ordering::AcqRel) {
            return;
        }
        self.sender.take();
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }

    fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }

    fn stats(&self) -> AudioRenderStats {
        AudioRenderStats {
            frames_accepted: self.accepted.load(Ordering::Relaxed),
            frames_dropped: self.dropped.load(Ordering::Relaxed),
        }
    }
}

impl Drop for PipeWireRender {
    fn drop(&mut self) {
        self.stop();
    }
}

fn timestamp_ns() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn endpoint(id: &str, name: &str, role: AudioEndpointRole) -> AudioEndpointDescriptor {
        AudioEndpointDescriptor {
            id: id.into(),
            name: name.into(),
            role,
            is_default: false,
        }
    }

    #[test]
    fn virtual_microphone_requires_both_endpoint_sides() {
        let render = endpoint(
            VOXPASSPORT_VIRTUAL_RENDER_ID,
            VOXPASSPORT_VIRTUAL_RENDER_NAME,
            AudioEndpointRole::RenderOutput,
        );
        let capture = endpoint(
            VOXPASSPORT_VIRTUAL_CAPTURE_ID,
            VOXPASSPORT_VIRTUAL_CAPTURE_NAME,
            AudioEndpointRole::PhysicalMicrophone,
        );
        assert!(!LinuxAudioPlatform::has_voxpassport_virtual_microphone(&[render.clone()]));
        assert!(LinuxAudioPlatform::has_voxpassport_virtual_microphone(&[render, capture]));
    }

    #[test]
    fn physical_source_with_invalid_monitor_index_is_not_a_monitor() {
        let source = json!({
            "name": "alsa_input.pci-0000_00_1f.3.analog-stereo",
            "monitor_of_sink": 4294967295u64,
            "monitor_of_sink_name": null,
            "properties": {"device.class": "sound"}
        });
        assert!(!source_is_monitor(
            &source,
            "alsa_input.pci-0000_00_1f.3.analog-stereo"
        ));
    }

    #[test]
    fn sink_monitor_is_classified_by_owner_name_or_suffix() {
        let by_owner = json!({
            "name": "custom-source",
            "monitor_of_sink": 0,
            "monitor_of_sink_name": "alsa_output.pci-0000_00_1f.3.analog-stereo"
        });
        assert!(source_is_monitor(&by_owner, "custom-source"));

        let by_suffix = json!({"name": "voxpassport_translation_sink.monitor"});
        assert!(source_is_monitor(
            &by_suffix,
            "voxpassport_translation_sink.monitor"
        ));
    }
}
