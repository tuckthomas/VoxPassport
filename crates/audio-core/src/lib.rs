//! LiveTranslator — Audio Core Engine (Rust)
//! Real-time audio processing, ring buffering, and RMS/peak calculation.

use livetranslator_protocol::{AudioBus, AudioFrame, SampleFormat};
use std::time::{SystemTime, UNIX_EPOCH};

pub struct AudioLevelMeter {
    pub rms_db: f32,
    pub peak_db: f32,
}

impl AudioLevelMeter {
    pub fn new() -> Self {
        Self {
            rms_db: -100.0,
            peak_db: -100.0,
        }
    }

    pub fn compute_s16le(&mut self, data: &[u8]) {
        if data.len() < 2 {
            return;
        }
        let n_samples = data.len() / 2;
        let mut sum_sq = 0.0f64;
        let mut max_abs = 0.0f32;

        for chunk in data.chunks_exact(2) {
            let sample = i16::from_le_bytes([chunk[0], chunk[1]]) as f32 / 32768.0;
            let abs_sample = sample.abs();
            sum_sq += (sample * sample) as f64;
            if abs_sample > max_abs {
                max_abs = abs_sample;
            }
        }

        let rms = (sum_sq / n_samples as f64).sqrt() as f32;
        self.rms_db = if rms > 1e-5 { 20.0 * rms.log10() } else { -100.0 };
        self.peak_db = if max_abs > 1e-5 { 20.0 * max_abs.log10() } else { -100.0 };
    }
}

pub struct AudioChunker {
    bus: AudioBus,
    sample_rate_hz: u32,
    channels: u16,
    chunk_samples: usize,
    sequence: u64,
    stream_id: String,
    meter: AudioLevelMeter,
}

impl AudioChunker {
    pub fn new(bus: AudioBus, sample_rate_hz: u32, channels: u16, chunk_duration_ms: u32) -> Self {
        let chunk_samples = (sample_rate_hz as u64 * chunk_duration_ms as u64 / 1000) as usize;
        let stream_id = format!("stream-{:?}-{}", bus, SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis());
        Self {
            bus,
            sample_rate_hz,
            channels,
            chunk_samples,
            sequence: 0,
            stream_id,
            meter: AudioLevelMeter::new(),
        }
    }

    pub fn process_raw_bytes(&mut self, data: Vec<u8>) -> AudioFrame {
        self.meter.compute_s16le(&data);
        let frame = AudioFrame {
            stream_id: self.stream_id.clone(),
            sequence: self.sequence,
            monotonic_timestamp_ns: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos() as u64,
            sample_rate_hz: self.sample_rate_hz,
            channels: self.channels,
            sample_format: SampleFormat::PcmS16le,
            data,
        };
        self.sequence += 1;
        frame
    }

    pub fn get_levels(&self) -> (f32, f32) {
        (self.meter.rms_db, self.meter.peak_db)
    }
}
