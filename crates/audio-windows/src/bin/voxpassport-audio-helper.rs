use livetranslator_audio_core::{
    AudioCaptureConfig, AudioEndpointRole, AudioPlatform, AudioRenderConfig,
};
use livetranslator_audio_windows::WindowsAudioPlatform;
use livetranslator_protocol::{AudioFrame, SampleFormat};
use serde_json::json;
use std::env;
use std::io::{self, Read, Write};
use std::time::Duration;

const FRAME_MAGIC: &[u8; 4] = b"VPF1";
const FRAME_HEADER_LEN: usize = 31;
const MAX_FRAME_BYTES: usize = 4 * 1024 * 1024;

fn main() {
    if let Err(error) = run() {
        eprintln!("voxpassport-audio-helper: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let command = args.next().unwrap_or_else(|| "help".into());
    let platform = WindowsAudioPlatform::new();
    match command.as_str() {
        "probe" => {
            let capabilities = platform.capabilities();
            let endpoint_count = platform.enumerate_endpoints()?.len();
            println!(
                "{}",
                serde_json::to_string(&json!({
                    "protocol": "voxpassport.native-audio.v1",
                    "platform": "windows",
                    "endpoint_count": endpoint_count,
                    "capabilities": {
                        "device_enumeration": capabilities.enumerate_microphones && capabilities.enumerate_render_endpoints,
                        "physical_microphone_capture": capabilities.capture_microphone,
                        "loopback_capture": capabilities.capture_loopback,
                        "render_output": capabilities.render_output,
                        "virtual_microphone_output": capabilities.virtual_microphone_output,
                    }
                }))?
            );
        }
        "devices" => {
            let devices = platform
                .enumerate_endpoints()?
                .into_iter()
                .map(|item| {
                    json!({
                        "id": item.id,
                        "name": item.name,
                        "role": role_name(item.role),
                        "is_default": item.is_default,
                    })
                })
                .collect::<Vec<_>>();
            println!("{}", serde_json::to_string(&json!({"schema_version": 1, "devices": devices}))?);
        }
        "capture-mic" | "capture-loopback" => {
            let config = parse_capture_config(args.collect())?;
            let mut stream = if command == "capture-mic" {
                platform.start_microphone_capture(config)?
            } else {
                platform.start_loopback_capture(config)?
            };
            let stdout = io::stdout();
            let mut output = stdout.lock();
            loop {
                match stream.recv_timeout(Duration::from_secs(1))? {
                    Some(frame) => write_frame(&mut output, &frame)?,
                    None if !stream.is_active() => break,
                    None => continue,
                }
            }
        }
        "render" => {
            let config = parse_render_config(args.collect())?;
            let mut stream = platform.start_render_output(config)?;
            let stdin = io::stdin();
            let mut input = stdin.lock();
            while let Some(frame) = read_frame(&mut input)? {
                // If the bounded queue is full, the stream deliberately drops
                // this newest frame instead of accumulating stale live audio.
                let _ = stream.try_write(frame)?;
            }
            stream.stop();
        }
        "help" | "--help" | "-h" => {
            println!("VoxPassport native audio helper");
            println!("  probe");
            println!("  devices");
            println!("  capture-mic [--endpoint ID] [--rate 16000] [--channels 1] [--chunk-ms 20] [--queue 8]");
            println!("  capture-loopback [same options]");
            println!("  render [--endpoint ID] [--rate 24000] [--channels 1] [--queue 16] < framed-pcm");
        }
        other => return Err(format!("unknown command {other:?}").into()),
    }
    Ok(())
}

fn parse_capture_config(args: Vec<String>) -> Result<AudioCaptureConfig, Box<dyn std::error::Error>> {
    let mut config = AudioCaptureConfig::default();
    let mut index = 0;
    while index < args.len() {
        let key = args[index].as_str();
        let value = args.get(index + 1).ok_or_else(|| format!("missing value for {key}"))?;
        match key {
            "--endpoint" => config.endpoint_id = Some(value.to_owned()),
            "--rate" => config.sample_rate_hz = value.parse()?,
            "--channels" => config.channels = value.parse()?,
            "--chunk-ms" => config.chunk_duration_ms = value.parse()?,
            "--queue" => config.queue_capacity = value.parse()?,
            other => return Err(format!("unknown capture option {other:?}").into()),
        }
        index += 2;
    }
    config.validate()?;
    Ok(config)
}

fn parse_render_config(args: Vec<String>) -> Result<AudioRenderConfig, Box<dyn std::error::Error>> {
    let mut config = AudioRenderConfig::default();
    let mut index = 0;
    while index < args.len() {
        let key = args[index].as_str();
        let value = args.get(index + 1).ok_or_else(|| format!("missing value for {key}"))?;
        match key {
            "--endpoint" => config.endpoint_id = Some(value.to_owned()),
            "--rate" => config.sample_rate_hz = value.parse()?,
            "--channels" => config.channels = value.parse()?,
            "--queue" => config.queue_capacity = value.parse()?,
            other => return Err(format!("unknown render option {other:?}").into()),
        }
        index += 2;
    }
    config.validate()?;
    Ok(config)
}

fn role_name(role: AudioEndpointRole) -> &'static str {
    match role {
        AudioEndpointRole::PhysicalMicrophone => "physical_microphone",
        AudioEndpointRole::RenderOutput => "render_output",
        AudioEndpointRole::LoopbackSource => "loopback_source",
        AudioEndpointRole::VirtualMicrophoneSink => "virtual_microphone_sink",
    }
}

/// Binary frame protocol consumed/produced by runtime/inference/native_audio_bridge.py.
/// magic[4] | sequence u64 | monotonic_ns u64 | sample_rate u32 |
/// channels u16 | sample_format u8 | payload_len u32 | payload bytes
fn write_frame(writer: &mut impl Write, frame: &AudioFrame) -> io::Result<()> {
    let format = match frame.sample_format {
        SampleFormat::PcmS16le => 1u8,
        SampleFormat::PcmF32le => 2u8,
    };
    writer.write_all(FRAME_MAGIC)?;
    writer.write_all(&frame.sequence.to_le_bytes())?;
    writer.write_all(&frame.monotonic_timestamp_ns.to_le_bytes())?;
    writer.write_all(&frame.sample_rate_hz.to_le_bytes())?;
    writer.write_all(&frame.channels.to_le_bytes())?;
    writer.write_all(&[format])?;
    writer.write_all(&(frame.data.len() as u32).to_le_bytes())?;
    writer.write_all(&frame.data)?;
    writer.flush()
}

fn read_frame(reader: &mut impl Read) -> Result<Option<AudioFrame>, Box<dyn std::error::Error>> {
    let mut header = [0u8; FRAME_HEADER_LEN];
    let first = reader.read(&mut header[..1])?;
    if first == 0 {
        return Ok(None);
    }
    reader.read_exact(&mut header[1..])?;
    if &header[0..4] != FRAME_MAGIC {
        return Err("native audio frame magic mismatch".into());
    }
    let sequence = u64::from_le_bytes(header[4..12].try_into()?);
    let timestamp = u64::from_le_bytes(header[12..20].try_into()?);
    let sample_rate = u32::from_le_bytes(header[20..24].try_into()?);
    let channels = u16::from_le_bytes(header[24..26].try_into()?);
    let sample_format = match header[26] {
        1 => SampleFormat::PcmS16le,
        2 => SampleFormat::PcmF32le,
        other => return Err(format!("unsupported native sample format id {other}").into()),
    };
    let payload_len = u32::from_le_bytes(header[27..31].try_into()?) as usize;
    if payload_len > MAX_FRAME_BYTES {
        return Err(format!("native audio frame exceeds {MAX_FRAME_BYTES} byte limit").into());
    }
    let mut data = vec![0u8; payload_len];
    reader.read_exact(&mut data)?;
    Ok(Some(AudioFrame {
        stream_id: "helper-render-input".into(),
        sequence,
        monotonic_timestamp_ns: timestamp,
        sample_rate_hz: sample_rate,
        channels,
        sample_format,
        data,
    }))
}
