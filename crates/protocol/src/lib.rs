//! LiveTranslator — Shared Rust Wire Protocol & Event Types
//! Matches `runtime/inference/protocol.py`

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SampleFormat {
    PcmS16le,
    PcmF32le,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AudioBus {
    PhysicalMic,
    RemoteConference,
    OutboundTranslatedTts,
    InboundTranslatedTts,
    VirtualMic,
    LocalMonitor,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LanguageCode {
    En,
    Ro,
    Auto,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioFrame {
    pub stream_id: String,
    pub sequence: u64,
    pub monotonic_timestamp_ns: u64,
    pub sample_rate_hz: u32,
    pub channels: u16,
    pub sample_format: SampleFormat,
    #[serde(with = "serde_bytes")]
    pub data: Vec<u8>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TranscriptState {
    Partial,
    Stable,
    Final,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranscriptEvent {
    pub utterance_id: String,
    pub revision: u32,
    pub source_language: LanguageCode,
    pub text: String,
    pub state: TranscriptState,
    pub is_partial: bool,
    pub is_final: bool,
    pub start_ms: Option<f64>,
    pub end_ms: Option<f64>,
    pub monotonic_timestamp_ns: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranslationEvent {
    pub utterance_id: String,
    pub segment_id: String,
    pub source_language: LanguageCode,
    pub target_language: LanguageCode,
    pub source_text: String,
    pub translated_text: String,
    pub is_committed: bool,
    pub created_monotonic_ns: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TtsAudioChunk {
    pub utterance_id: String,
    pub segment_id: String,
    pub sequence: u32,
    pub sample_rate_hz: u32,
    pub sample_format: SampleFormat,
    #[serde(with = "serde_bytes")]
    pub data: Vec<u8>,
    pub is_final_chunk: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptionEvent {
    pub event_type: String,
    pub utterance_id: String,
    pub language: LanguageCode,
    pub text: String,
    pub is_final: bool,
    pub monotonic_timestamp_ns: u64,
}
