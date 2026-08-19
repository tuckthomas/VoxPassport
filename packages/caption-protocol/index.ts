/**
 * LiveTranslator — Caption Protocol Types & Schema
 * Shared contract for Companion <-> Browser Extension <-> Desktop Overlay IPC.
 */

export const ProtocolVersion = "1.0.0";

export enum CaptionEventType {
  PartialSource = "partial_source",
  FinalSource = "final_source",
  CommittedTranslation = "committed_translation",
  FinalTranslation = "final_translation",
  PlayingTts = "playing_tts",
}

export enum PipelineDirection {
  Outbound = "outbound", // EN -> RO
  Inbound = "inbound",   // RO -> EN
}

export interface CaptionPacket {
  version: string;
  type: "caption";
  event_type: CaptionEventType;
  direction: PipelineDirection;
  utterance_id: string;
  segment_id?: string;
  source_language: string;
  target_language: string;
  text: string;
  is_final: boolean;
  timestamp_ns: number;
  latency_ms?: number;
}

export interface TelemetryPacket {
  version: string;
  type: "telemetry";
  e2e_p50_ms: number;
  e2e_p95_ms: number;
  mic_level_db: number;
  conf_level_db: number;
  active_mode: string;
  runtime_tier: string;
  active_asr_model: string;
  active_mt_model: string;
  active_tts_model: string;
}

export interface ControlCommand {
  type: "control";
  action: "set_mode" | "set_tts_mode" | "set_active_model" | "mute" | "unmute";
  payload: Record<string, any>;
}
