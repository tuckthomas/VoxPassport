import { Platform } from 'react-native';
import type { AccountUser, AuthResponse, ProviderCredentialSummary } from './contracts';

export class AccountApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = 'AccountApiError';
  }
}

export class AccountApi {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.trim().replace(/\/+$/, '');
  }

  private async request<T>(path: string, init?: RequestInit, accessToken?: string | null): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        'X-VoxPassport-Client-Kind': Platform.OS === 'web' ? 'web' : 'native',
        'X-VoxPassport-Client-Label': `${Platform.OS}-expo-client`,
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...init?.headers,
      },
    });
    if (response.status === 204) return undefined as T;
    const raw = await response.text();
    if (!response.ok) {
      let message = raw || `${response.status} ${response.statusText}`;
      try {
        const payload = JSON.parse(raw) as { detail?: string; error?: string };
        message = payload.detail || payload.error || message;
      } catch {
        // Preserve plain-text response.
      }
      throw new AccountApiError(response.status, message);
    }
    return raw ? JSON.parse(raw) as T : undefined as T;
  }

  signup(email: string, password: string, displayName?: string): Promise<AuthResponse> {
    return this.request('/v1/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name: displayName?.trim() || null }),
    });
  }

  login(email: string, password: string): Promise<AuthResponse> {
    return this.request('/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  }

  refresh(refreshToken?: string | null): Promise<AuthResponse> {
    return this.request('/v1/auth/refresh', {
      method: 'POST',
      body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
    });
  }

  logout(refreshToken?: string | null): Promise<void> {
    return this.request('/v1/auth/logout', {
      method: 'POST',
      body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
    });
  }

  logoutAll(accessToken: string): Promise<void> {
    return this.request('/v1/auth/logout-all', { method: 'POST' }, accessToken);
  }

  me(accessToken: string): Promise<AccountUser> {
    return this.request('/v1/auth/me', undefined, accessToken);
  }

  requestEmailVerification(email: string): Promise<{ accepted: boolean }> {
    return this.request('/v1/auth/email-verification/request', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  confirmEmailVerification(token: string): Promise<AccountUser> {
    return this.request('/v1/auth/email-verification/confirm', {
      method: 'POST',
      body: JSON.stringify({ token }),
    });
  }

  requestPasswordReset(email: string): Promise<{ accepted: boolean }> {
    return this.request('/v1/auth/password-reset/request', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  confirmPasswordReset(token: string, newPassword: string): Promise<void> {
    return this.request('/v1/auth/password-reset/confirm', {
      method: 'POST',
      body: JSON.stringify({ token, new_password: newPassword }),
    });
  }

  changePassword(currentPassword: string, newPassword: string, accessToken: string): Promise<AuthResponse> {
    return this.request('/v1/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }, accessToken);
  }

  providerCredentials(accessToken: string): Promise<ProviderCredentialSummary[]> {
    return this.request('/v1/provider-credentials', undefined, accessToken);
  }

  saveProviderCredential(
    provider: string,
    secret: string,
    accessToken: string,
    label = 'default',
  ): Promise<ProviderCredentialSummary> {
    return this.request(`/v1/provider-credentials/${encodeURIComponent(provider)}`, {
      method: 'PUT',
      body: JSON.stringify({ label, secret }),
    }, accessToken);
  }

  deleteProviderCredential(provider: string, accessToken: string, label = 'default'): Promise<void> {
    const query = new URLSearchParams({ label }).toString();
    return this.request(`/v1/provider-credentials/${encodeURIComponent(provider)}?${query}`, {
      method: 'DELETE',
    }, accessToken);
  }
}
