export const SESSION_PROTOCOL = 'voxpassport.session.v1' as const;

export type RuntimeBootstrap = {
  protocol_version: string;
  runtime: 'local';
  api_base_url: string;
  captions_websocket_url: string;
  resources_websocket_url: string;
  capabilities: string[];
  app_version?: string;
};

export type RuntimeStatus = {
  status: string;
  mode: string;
  tts_mode: string;
  user_language: string;
  remote_language: string;
  active_slots: Record<string, string>;
  model_residency: string;
  models_loaded: boolean;
};

export type ModelEntry = {
  model_id: string;
  name: string;
  capability: string;
  provider?: string;
  upstream_id?: string;
  installation_status?: string;
  is_active?: boolean;
  required_runtime?: string;
  runtime_requirements?: Record<string, unknown>;
  voice_cloning_support?: boolean;
  cross_lingual_voice_cloning?: boolean;
  supported_source_languages?: string[];
  supported_target_languages?: string[];
};

export type VoiceProfile = {
  profile_id: string;
  profile_name: string;
  status?: string;
  ref_lang?: string;
  pitch_hz?: number;
  has_audio?: boolean;
  has_translation_audio?: boolean;
  is_active?: boolean;
};

export type VoiceProfilesResponse = {
  profiles: VoiceProfile[];
  active_id: string;
};

export type TranslationResponse = {
  source_text: string;
  translated_text: string;
  source_language: string;
  target_language: string;
  latency_ms: number;
};

export type SessionFeature = 'captions' | 'translation' | 'tts' | 'voice_clone' | 'diarization';

export type SessionAllocationRequest = {
  protocol_version: typeof SESSION_PROTOCOL;
  source_language: string;
  target_language: string;
  requested_features: SessionFeature[];
  preferred_region?: string;
  preferred_models?: Partial<Record<'asr' | 'translation' | 'tts', string>>;
  audio: {
    sample_rate_hz: number;
    channels: number;
    codec: 'pcm_s16le' | 'opus';
  };
};

export type PricingQuote = {
  currency: 'USD';
  price_per_audio_minute: number;
  billing_unit: 'audio_minute';
  pricing_tier: string;
};

export type SessionAllocation = {
  protocol_version: typeof SESSION_PROTOCOL;
  session_id: string;
  media_mode: 'direct_worker' | 'relay';
  worker: {
    websocket_url: string;
    region: string;
    capabilities: string[];
  };
  credential: {
    token: string;
    expires_at: string;
  };
  pricing: PricingQuote;
};

export type SessionControlEvent =
  | { type: 'auth'; protocol_version: typeof SESSION_PROTOCOL; session_id: string; token: string }
  | { type: 'state'; state: 'ready' | 'listening' | 'processing' | 'speaking' | 'closed'; timestamp_ms: number }
  | { type: 'caption'; kind: 'source_partial' | 'source_final' | 'translation_partial' | 'translation_final'; text: string; sequence: number; timestamp_ms: number }
  | { type: 'latency'; metric: 'capture_to_partial_caption' | 'capture_to_final_translation' | 'capture_to_first_audio'; milliseconds: number }
  | { type: 'error'; code: string; message: string; recoverable: boolean };
