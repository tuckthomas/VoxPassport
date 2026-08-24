import type {
  LiveTranslationSessionStartRequest,
  LiveTranslationSessionStatus,
} from './contracts';

export class LiveTranslationClient {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.trim().replace(/\/+$/, '');
  }

  status(): Promise<LiveTranslationSessionStatus> {
    return this.request('/api/translation/live');
  }

  start(request: LiveTranslationSessionStartRequest): Promise<LiveTranslationSessionStatus> {
    return this.request('/api/translation/live/start', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  stop(): Promise<LiveTranslationSessionStatus> {
    return this.request('/api/translation/live/stop', { method: 'POST' });
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
    const body = await response.text();
    if (!response.ok) {
      try {
        const payload = JSON.parse(body) as { error?: string; detail?: string };
        throw new Error(payload.error || payload.detail || `${response.status} ${response.statusText}`);
      } catch (error) {
        if (error instanceof SyntaxError) throw new Error(`${response.status} ${response.statusText}: ${body}`);
        throw error;
      }
    }
    return JSON.parse(body) as T;
  }
}
