//! LiveTranslator — Windows WASAPI Audio Capture & Render Endpoint
//! Provides physical mic capture, system loopback capture, and virtual mic output.

use livetranslator_audio_core::AudioChunker;
use livetranslator_protocol::{AudioBus, AudioFrame};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

pub struct WasapiAudioDevice {
    pub id: String,
    pub name: String,
    pub is_default: bool,
    pub is_loopback: bool,
}

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

    pub fn feed_pcm_data(&mut self, data: Vec<u8>) -> Option<AudioFrame> {
        if !self.is_active() {
            return None;
        }
        Some(self.chunker.process_raw_bytes(data))
    }
}
