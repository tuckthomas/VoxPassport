import { Platform } from 'react-native';
import type {
  DesktopAudioDevicesResponse,
  DesktopAudioStatus,
  LanguageConfiguration,
  ModelEntry,
  ModelInstallProgress,
  ModelMutationResponse,
  ModelStorageSettings,
  ModelStorageBrowseResult,
  NativeAudioRouting,
  NativeAudioRoutingPatch,
  ResourceSnapshot,
  RemoteModelEndpoint,
  RuntimeBootstrap,
  RuntimeStatus,
  TranslationResponse,
  TranslationStrategiesResponse,
  TranslationStrategyStatus,
  TranslationStrategyValidation,
  VoiceMutationResponse,
  VoiceProfilesResponse,
  VoiceStageResponse,
} from './contracts';

export class VoxPassportApi {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.trim().replace(/\/+$/, '');
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const isFormData = typeof FormData !== 'undefined' && init?.body instanceof FormData;
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body && !isFormData ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
    if (!response.ok) {
      const responseBody = await response.text();
      throw new Error(apiErrorMessage(response.status, responseBody, response.statusText));
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  private async requestBinary(path: string, init?: RequestInit): Promise<ArrayBuffer> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'audio/wav, application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
    if (!response.ok) {
      const responseBody = await response.text();
      throw new Error(apiErrorMessage(response.status, responseBody, response.statusText));
    }
    return response.arrayBuffer();
  }

  mediaUrl(path: string): string {
    if (/^https?:\/\//i.test(path)) return path;
    return `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
  }

  bootstrap(): Promise<RuntimeBootstrap> {
    return this.request('/api/client/bootstrap');
  }

  status(): Promise<RuntimeStatus> {
    return this.request('/api/status');
  }

  resources(): Promise<ResourceSnapshot> {
    return this.request('/api/resources');
  }

  audioStatus(): Promise<DesktopAudioStatus> {
    return this.request('/api/audio/status');
  }

  audioDevices(): Promise<DesktopAudioDevicesResponse> {
    return this.request('/api/audio/devices');
  }

  audioRouting(): Promise<NativeAudioRouting> {
    return this.request('/api/audio/routing');
  }

  updateAudioRouting(patch: NativeAudioRoutingPatch): Promise<NativeAudioRouting> {
    return this.request('/api/audio/routing', {
      method: 'PUT',
      body: JSON.stringify(patch),
    });
  }

  confirmVirtualMicrophone(confirmed: boolean): Promise<NativeAudioRouting> {
    return this.request('/api/audio/routing/confirm-virtual-microphone', {
      method: 'POST',
      body: JSON.stringify({ confirmed }),
    });
  }

  translationStrategies(): Promise<TranslationStrategiesResponse> {
    return this.request('/api/translation/strategies');
  }

  translationStrategyStatus(): Promise<TranslationStrategyStatus> {
    return this.request('/api/translation/strategy');
  }

  validateTranslationStrategy(strategyId: string, sourceLanguage: string, targetLanguage: string): Promise<TranslationStrategyValidation> {
    return this.request('/api/translation/strategy/validate', {
      method: 'POST',
      body: JSON.stringify({
        strategy_id: strategyId,
        source_language: sourceLanguage,
        target_language: targetLanguage,
      }),
    });
  }

  activateTranslationStrategy(strategyId: string, sourceLanguage: string, targetLanguage: string): Promise<TranslationStrategyStatus> {
    return this.request('/api/translation/strategy/activate', {
      method: 'POST',
      body: JSON.stringify({
        strategy_id: strategyId,
        source_language: sourceLanguage,
        target_language: targetLanguage,
      }),
    });
  }

  languages(): Promise<LanguageConfiguration> {
    return this.request('/api/languages');
  }

  models(): Promise<ModelEntry[]> {
    return this.request('/api/models/available');
  }

  installModel(modelId: string, upstreamId?: string, revision?: string): Promise<ModelMutationResponse> {
    return this.request('/api/models/install', {
      method: 'POST',
      body: JSON.stringify({ model_id: modelId, upstream_id: upstreamId, revision }),
    });
  }

  modelInstallProgress(modelId: string): Promise<ModelInstallProgress> {
    return this.request(`/api/models/progress?model_id=${encodeURIComponent(modelId)}`);
  }

  uninstallModel(modelId: string): Promise<ModelMutationResponse> {
    return this.request('/api/models/uninstall', {
      method: 'POST',
      body: JSON.stringify({ model_id: modelId }),
    });
  }

  activateModel(capability: string, modelId: string): Promise<ModelMutationResponse> {
    return this.request('/api/models/active', {
      method: 'POST',
      body: JSON.stringify({ capability, model_id: modelId }),
    });
  }

  modelStorage(): Promise<ModelStorageSettings> {
    return this.request('/api/settings/model-storage');
  }

  saveModelStorage(modelStoreDir: string): Promise<ModelStorageSettings> {
    return this.request('/api/settings/model-storage', { method: 'POST', body: JSON.stringify({ model_store_dir: modelStoreDir }) });
  }

  browseModelStorage(initialDirectory: string): Promise<ModelStorageBrowseResult> {
    return this.request('/api/settings/model-storage/browse', { method: 'POST', body: JSON.stringify({ initial_directory: initialDirectory }) });
  }

  remoteModelEndpoints(): Promise<RemoteModelEndpoint[]> {
    return this.request('/api/remote-endpoints');
  }

  createRemoteModelEndpoint(input: Omit<RemoteModelEndpoint, 'endpoint_id'>): Promise<{ success: boolean; endpoint_id?: string; error?: string }> {
    return this.request('/api/remote-endpoints', { method: 'POST', body: JSON.stringify(input) });
  }

  voiceProfiles(): Promise<VoiceProfilesResponse> {
    return this.request('/api/voice/profiles');
  }

  activateVoiceProfile(profileId: string): Promise<VoiceMutationResponse> {
    return this.request('/api/voice/activate', {
      method: 'POST',
      body: JSON.stringify({ profile_id: profileId }),
    });
  }

  deleteVoiceProfile(profileId: string): Promise<VoiceMutationResponse> {
    return this.request(`/api/voice/profiles/${encodeURIComponent(profileId)}`, { method: 'DELETE' });
  }

  async stageVoiceProfile(input: {
    audioUri: string;
    name: string;
    transcript: string;
    refLang: string;
    previewLang: string;
    previewText: string;
    cloneModel?: string;
  }): Promise<VoiceStageResponse> {
    const form = new FormData();
    form.append('name', input.name);
    form.append('transcript', input.transcript);
    form.append('ref_lang', input.refLang);
    form.append('preview_lang', input.previewLang);
    form.append('preview_text', input.previewText);
    if (input.cloneModel) form.append('clone_model', input.cloneModel);

    if (Platform.OS === 'web') {
      const blob = await (await fetch(input.audioUri)).blob();
      form.append('audio', blob, 'reference.webm');
    } else {
      form.append('audio', {
        uri: input.audioUri,
        name: 'reference.m4a',
        type: 'audio/mp4',
      } as unknown as Blob);
    }

    return this.request('/api/voice/stage', { method: 'POST', body: form });
  }

  commitVoiceStage(name: string): Promise<VoiceMutationResponse> {
    return this.request('/api/voice/commit_stage', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  clearVoiceStage(): Promise<{ success: boolean }> {
    return this.request('/api/voice/clear_stage', { method: 'POST' });
  }

  async synthesizeVoicePreview(profileId: string, text: string, target: string, cloneModel?: string): Promise<void> {
    await this.requestBinary('/api/synthesize', {
      method: 'POST',
      body: JSON.stringify({
        profile_id: profileId,
        text,
        target,
        preview: true,
        clone_model: cloneModel,
      }),
    });
  }

  translate(text: string, source: string, target: string): Promise<TranslationResponse> {
    return this.request('/api/translate', {
      method: 'POST',
      body: JSON.stringify({ text, source, target }),
    });
  }
}

function apiErrorMessage(status: number, responseBody: string, statusText = ''): string {
  try {
    const payload = JSON.parse(responseBody) as { error?: string; detail?: string };
    if (payload.error && payload.detail) return `${payload.error}: ${payload.detail}`;
    if (payload.error) return payload.error;
    if (payload.detail) return payload.detail;
  } catch {
    // Non-JSON errors fall through to the HTTP status/body summary.
  }
  const detail = responseBody.trim();
  const prefix = `${status}${statusText ? ` ${statusText}` : ''}`;
  return detail ? `${prefix}: ${detail}` : prefix;
}
