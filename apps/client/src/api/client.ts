import type {
  DesktopAudioDevicesResponse,
  DesktopAudioStatus,
  LanguageConfiguration,
  ModelEntry,
  RuntimeBootstrap,
  RuntimeStatus,
  TranslationResponse,
  TranslationStrategiesResponse,
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
      const responseBody = await response.text();
      throw new Error(apiErrorMessage(response.status, responseBody, response.statusText));
    }
    return response.json() as Promise<T>;
  }

  bootstrap(): Promise<RuntimeBootstrap> {
    return this.request('/api/client/bootstrap');
  }

  status(): Promise<RuntimeStatus> {
    return this.request('/api/status');
  }

  audioStatus(): Promise<DesktopAudioStatus> {
    return this.request('/api/audio/status');
  }

  audioDevices(): Promise<DesktopAudioDevicesResponse> {
    return this.request('/api/audio/devices');
  }

  translationStrategies(): Promise<TranslationStrategiesResponse> {
    return this.request('/api/translation/strategies');
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

function apiErrorMessage(status: number, responseBody: string, statusText = ''): string {
  try {
    const payload = JSON.parse(responseBody) as { error?: string; detail?: string };
    if (payload.error && payload.detail) return `${payload.error}: ${payload.detail}`;
    if (payload.error) return payload.error;
  } catch {
    // Non-JSON errors fall through to the HTTP status/body summary.
  }
  const detail = responseBody.trim();
  const prefix = `${status}${statusText ? ` ${statusText}` : ''}`;
  return detail ? `${prefix}: ${detail}` : prefix;
}
