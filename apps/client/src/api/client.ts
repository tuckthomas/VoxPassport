import type {
  LanguageConfiguration,
  ModelEntry,
  RuntimeBootstrap,
  RuntimeStatus,
  TranslationResponse,
  VoiceProfilesResponse,
} from './contracts';

export class VoxPassportApi {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.trim().replace(/\/+$/, '');
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json() as { error?: string };
        if (body.error) message = body.error;
      } catch {
        // Preserve the HTTP error when a response is not JSON.
      }
      throw new Error(message);
    }
    return response.json() as Promise<T>;
  }

  bootstrap(): Promise<RuntimeBootstrap> {
    return this.request('/api/client/bootstrap');
  }

  status(): Promise<RuntimeStatus> {
    return this.request('/api/status');
  }

  languages(): Promise<LanguageConfiguration> {
    return this.request('/api/languages');
  }

  models(): Promise<ModelEntry[]> {
    return this.request('/api/models/available');
  }

  voiceProfiles(): Promise<VoiceProfilesResponse> {
    return this.request('/api/voice/profiles');
  }

  translate(text: string, source: string, target: string): Promise<TranslationResponse> {
    return this.request('/api/translate', {
      method: 'POST',
      body: JSON.stringify({ text, source, target }),
    });
  }

  activateModel(capability: string, modelId: string): Promise<{ success: boolean; model_id: string; active_slots: Record<string, string> }> {
    return this.request('/api/models/active', {
      method: 'POST',
      body: JSON.stringify({ capability, model_id: modelId }),
    });
  }
}
