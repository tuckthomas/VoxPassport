export const SESSION_PROTOCOL = 'voxpassport.session.v1' as const;
export const CLIENT_PROTOCOL = 'voxpassport.client.v1' as const;

export type RuntimeBootstrap = {
  protocol_version: string;
  runtime: 'local';
  api_base_url: string;
  captions_websocket_url: string;
  resources_websocket_url: string;
  audio_status_url: string;
  audio_devices_url: string;
  audio_routing_url: string;
  translation_strategies_url: string;
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
  translation_strategy?: TranslationStrategyStatus;
};

export type DesktopAudioCapabilities = {
  device_enumeration: boolean;
  physical_microphone_capture: boolean;
  loopback_capture: boolean;
  render_output: boolean;
  virtual_microphone_output: boolean;
};

export type DesktopAudioStatus = {
  schema_version: number;
  transport: 'runtime_native_service';
  platform: string;
  service_connected: boolean;
  capabilities: DesktopAudioCapabilities;
  note: string;
};

export type DesktopAudioDeviceRole =
  | 'physical_microphone'
  | 'render_output'
  | 'loopback_source'
  | 'virtual_microphone_sink';

export type DesktopAudioDevice = {
  id: string;
  name: string;
  role: DesktopAudioDeviceRole;
  is_default: boolean;
};

export type DesktopAudioDevicesResponse = {
  schema_version: number;
  devices: DesktopAudioDevice[];
};

export type NativeAudioRouting = {
  schema_version: number;
  microphone_endpoint_id: string | null;
  loopback_endpoint_id: string | null;
  monitor_render_endpoint_id: string | null;
  virtual_microphone_render_endpoint_id: string | null;
  virtual_microphone_capture_endpoint_id: string | null;
  virtual_microphone_validated: boolean;
  available: boolean;
  selection_status: {
    microphone: boolean;
    loopback: boolean;
    monitor: boolean;
    virtual_microphone_render: boolean;
    virtual_microphone_capture: boolean;
  };
  virtual_microphone_configured: boolean;
  virtual_microphone_ready: boolean;
};

export type NativeAudioRoutingPatch = Partial<Pick<NativeAudioRouting,
  | 'microphone_endpoint_id'
  | 'loopback_endpoint_id'
  | 'monitor_render_endpoint_id'
  | 'virtual_microphone_render_endpoint_id'
  | 'virtual_microphone_capture_endpoint_id'
>>;

export type TranslationStrategyExecutionMode =
  | 'local'
  | 'byo_api'
  | 'self_hosted'
  | 'managed_cloud';

export type TranslationStrategyAuthKind =
  | 'none'
  | 'api_key'
  | 'oauth'
  | 'session_token';

export type TranslationStrategyDescriptor = {
  strategy_id: string;
  display_name: string;
  provider: string;
  model_id: string;
  kind: 'direct_speech_translation';
  capability: 'DIRECT_SPEECH_TRANSLATION';
  execution_mode: TranslationStrategyExecutionMode;
  transport: string;
  auth_kind: TranslationStrategyAuthKind;
  auth_env?: string | null;
  streaming: boolean;
  bidirectional: boolean;
  voice_preservation: boolean;
  language_discovery: string;
  confirmed_languages: string[];
  lifecycle: string;
  metadata: Record<string, unknown>;
};

export type TranslationStrategiesResponse = {
  schema_version: number;
  strategies: TranslationStrategyDescriptor[];
};

export type TranslationStrategyStatus = {
  schema_version: number;
  kind: 'modular_pipeline' | 'direct_speech_translation';
  strategy_id: string;
  transitioning: boolean;
  direct_loaded: boolean;
  cascade_active: boolean;
};

export type TranslationStrategyValidation = {
  valid: boolean;
  strategy_id: string;
  kind: 'modular_pipeline' | 'direct_speech_translation';
  reason: string;
  auth_configured: boolean | null;
};

export type LanguageConfiguration = {
  user_language: string;
  remote_language: string;
  supported: string[];
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
