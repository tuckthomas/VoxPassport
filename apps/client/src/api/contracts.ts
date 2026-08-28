export const SESSION_PROTOCOL = 'voxpassport.session.v1' as const;
export const CLIENT_PROTOCOL = 'voxpassport.client.v1' as const;

export type DeploymentClientConfig = {
  local_only: boolean;
  accounts: {
    enabled: boolean;
    api_url: string | null;
  };
  security: {
    abuse_controls_enabled: boolean;
  };
};

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
  deployment: DeploymentClientConfig;
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
  live_translation_session?: LiveTranslationSessionStatus | null;
};

export type ResourceSnapshot = {
  sampled_at_ms: number;
  cpu: { usage_percent: number; logical_cores: number };
  memory: { used_gb: number; total_gb: number; usage_percent: number };
  gpu: {
    available: boolean;
    name: string;
    usage_percent: number | null;
    memory_used_gb: number;
    memory_total_gb: number;
    memory_percent: number;
    temperature_c: number | null;
    source: string;
  };
  tts_runtime?: Record<string, unknown>;
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

export type LiveTranslationMode = 'full_duplex' | 'outbound' | 'inbound';

export type LiveTranslationLegCaptions = Record<string, {
  source: string;
  translation: string;
}>;

export type LiveTranslationSessionStatus = {
  schema_version: number;
  active: boolean;
  session_id: string | null;
  strategy_id: string | null;
  source_language: string | null;
  target_language: string | null;
  mode: LiveTranslationMode | null;
  frames_forwarded: number;
  translated_audio_chunks: number;
  source_caption: string;
  translated_caption: string;
  leg_captions: LiveTranslationLegCaptions;
  state: string;
  error: string | null;
};

export type LiveTranslationSessionStartRequest = {
  source_language: string;
  target_language: string;
  mode: LiveTranslationMode;
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
  revision?: string;
  installation_status?: 'not_installed' | 'downloading' | 'installing' | 'installed' | 'failed' | string;
  recommendation_state?: 'RECOMMENDED_FOR_LOCAL_BENCHMARK' | 'RECOMMENDED_UPGRADE' | 'CANDIDATE' | 'WATCH' | 'IGNORE' | string;
  installable?: boolean;
  installation_reason?: string | null;
  is_active?: boolean;
  is_pinned?: boolean;
  is_pipeline_enabled?: boolean;
  required_runtime?: string;
  runtime_requirements?: Record<string, unknown>;
  estimated_download_size_gb?: number;
  installed_size_gb?: number | null;
  expected_vram_tiers?: Record<string, string>;
  expected_ram_gb?: number | null;
  license?: string;
  commercial_use?: string;
  voice_cloning_support?: boolean;
  cross_lingual_voice_cloning?: boolean;
  supported_source_languages?: string[];
  supported_target_languages?: string[];
};

export type ModelInstallProgress = {
  model_id: string;
  phase: 'idle' | 'downloading' | 'installing' | 'done' | 'failed' | string;
  percent: number;
  bytes_downloaded?: number;
  bytes_total?: number;
  error?: string | null;
};

export type ModelMutationResponse = {
  success: boolean;
  model_id?: string;
  ui_model_id?: string;
  active_slots?: Record<string, string>;
  error?: string;
};

export type ModelStorageSettings = { model_store_dir: string; success?: boolean; error?: string };
export type ModelStorageBrowseResult = { success: boolean; cancelled: boolean; model_store_dir: string | null; error?: string };

export type RemoteModelEndpoint = {
  endpoint_id: string;
  name: string;
  base_url: string;
  capabilities: string[];
  auth_token_env?: string;
  selected_model_id?: string;
};

export type VoiceProfile = {
  profile_id: string;
  profile_name: string;
  status?: string;
  ref_lang?: string;
  pitch_hz?: number;
  has_audio?: boolean;
  has_translation_audio?: boolean;
  translation_url?: string;
  preview_lang?: string;
  preview_text?: string;
  last_preview_model?: string;
  is_active?: boolean;
};

export type VoiceProfilesResponse = {
  profiles: VoiceProfile[];
  active_id: string;
};

export type VoiceStageResponse = {
  success: boolean;
  profile_id: string;
  profile_name: string;
  pitch_hz?: number;
  preview_model?: string;
  engine_name?: string;
  has_preview?: boolean;
  preview_url?: string;
  reference_url?: string;
  preview_error?: string;
  error?: string;
};

export type VoiceMutationResponse = {
  success: boolean;
  profile_id?: string;
  profile_name?: string;
  active_id?: string;
  deleted_id?: string;
  error?: string;
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
