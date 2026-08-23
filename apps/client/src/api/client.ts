import { requestLocalRuntime } from '@/desktop/bridge';
import type {
  LanguageConfiguration,
  ModelEntry,
  RuntimeBootstrap,
  RuntimeStatus,
  TranslationResponse,
  VoiceProfilesResponse,
} from './contracts';

export type VoxPassportApiOptions = {
  nativeLocal?: boolean;
};

export class VoxPassportApi {
  readonly baseUrl: string;
  private readonly nativeLocal: boolean;

  constructor(baseUrl: string, options: VoxPassportApiOptions = {}) {
    this.baseUrl = baseUrl.trim().replace(/\/+$/, '');
    this.nativeLocal = options.nativeLocal === true;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const method = String(init?.method ?? 'GET').toUpperCase();
    const body = typeof init?.body === 'string' ? init.body : null;

    if (this.nativeLocal && (!init?.body || body !== null)) {
      const nativeResponse = await requestLocalRuntime(this.baseUrl, path, method, body);
      if (nativeResponse) {
        if (nativeResponse.status < 200 || nativeResponse.status >= 300) {
          throw new Error(apiErrorMessage(nativeResponse.status, nativeResponse.body));
        }
        try {
          return JSON.parse(nativeResponse.body) as T;
        } catch (error) {
          throw new Error(`Local runtime returned invalid JSON for ${path}: ${String(error)}`);
        }
      }
    }

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
