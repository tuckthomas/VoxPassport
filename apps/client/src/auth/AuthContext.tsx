import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';
import { Platform } from 'react-native';
import { VoxPassportApi } from '@/api/client';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { getSetting, setSetting } from '@/storage/settingsStorage';
import { AccountApi, AccountApiError } from './AccountApi';
import { loadNativeRefreshToken, saveNativeRefreshToken } from './authStorage';
import type { AccountUser, AuthResponse, ProviderCredentialSummary } from './contracts';

const DEFAULT_ACCOUNT_API_URL = 'http://127.0.0.1:8780';

type AuthContextValue = {
  ready: boolean;
  enabled: boolean;
  localOnly: boolean;
  emailVerificationRequired: boolean;
  user: AccountUser | null;
  accessToken: string | null;
  accountBaseUrl: string;
  error: string;
  setAccountBaseUrl: (url: string) => Promise<void>;
  signup: (email: string, password: string, displayName?: string) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<void>;
  refreshSession: () => Promise<boolean>;
  requestEmailVerification: (email: string) => Promise<void>;
  confirmEmailVerification: (token: string) => Promise<AccountUser>;
  requestPasswordReset: (email: string) => Promise<void>;
  confirmPasswordReset: (token: string, newPassword: string) => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  providerCredentials: () => Promise<ProviderCredentialSummary[]>;
  saveProviderCredential: (provider: string, secret: string, label?: string) => Promise<ProviderCredentialSummary>;
  deleteProviderCredential: (provider: string, label?: string) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '') || DEFAULT_ACCOUNT_API_URL;
}

export function AuthProvider({ children }: PropsWithChildren) {
  const target = useRuntimeTarget();
  const [accountBaseUrl, setAccountBaseUrlState] = useState(DEFAULT_ACCOUNT_API_URL);
  const [baseReady, setBaseReady] = useState(false);
  const [deploymentReady, setDeploymentReady] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [localOnly, setLocalOnly] = useState(false);
  const [emailVerificationRequired, setEmailVerificationRequired] = useState(false);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<AccountUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [accessExpiresAt, setAccessExpiresAt] = useState(0);
  const [error, setError] = useState('');
  const refreshInFlight = useRef<Promise<boolean> | null>(null);

  const api = useMemo(() => new AccountApi(accountBaseUrl), [accountBaseUrl]);

  useEffect(() => {
    let active = true;
    getSetting('account.apiBaseUrl')
      .then((saved) => {
        if (!active) return;
        if (saved) setAccountBaseUrlState(normalizeBaseUrl(saved));
        setBaseReady(true);
      })
      .catch(() => setBaseReady(true));
    return () => { active = false; };
  }, []);

  const clearAuth = useCallback(async () => {
    setAccessToken(null);
    setUser(null);
    setAccessExpiresAt(0);
    if (Platform.OS !== 'web') await saveNativeRefreshToken(null);
  }, []);

  useEffect(() => {
    if (!target.ready) return;
    let active = true;
    const runtimeApi = new VoxPassportApi(target.activeBaseUrl);
    runtimeApi.bootstrap()
      .then(async (bootstrap) => {
        if (!active) return;
        const nextEnabled = Boolean(bootstrap.deployment?.accounts?.enabled);
        const nextLocalOnly = Boolean(bootstrap.deployment?.local_only);
        setEnabled(nextEnabled);
        setLocalOnly(nextLocalOnly);
        if (nextEnabled && bootstrap.deployment.accounts.api_url) {
          setAccountBaseUrlState(normalizeBaseUrl(bootstrap.deployment.accounts.api_url));
        }
        if (!nextEnabled) await clearAuth();
        setDeploymentReady(true);
      })
      .catch(() => {
        if (!active) return;
        setEnabled(true);
        setLocalOnly(false);
        setDeploymentReady(true);
      });
    return () => { active = false; };
  }, [target.ready, target.activeBaseUrl, clearAuth]);

  useEffect(() => {
    if (!baseReady || !deploymentReady || !enabled) {
      if (!enabled) setEmailVerificationRequired(false);
      return;
    }
    let active = true;
    api.config()
      .then((config) => {
        if (!active) return;
        setEmailVerificationRequired(Boolean(config.require_email_verification));
      })
      .catch(() => {
        if (active) setEmailVerificationRequired(false);
      });
    return () => { active = false; };
  }, [api, baseReady, deploymentReady, enabled]);

  const applyAuth = useCallback(async (result: AuthResponse) => {
    setAccessToken(result.access_token);
    setUser(result.user);
    setAccessExpiresAt(Date.now() + result.expires_in_seconds * 1000);
    if (Platform.OS !== 'web') await saveNativeRefreshToken(result.refresh_token);
    setError('');
  }, []);

  const refreshSession = useCallback(async (): Promise<boolean> => {
    if (!enabled) {
      await clearAuth();
      return false;
    }
    if (refreshInFlight.current) return refreshInFlight.current;
    const attempt = (async () => {
      try {
        const nativeRefresh = Platform.OS === 'web' ? null : await loadNativeRefreshToken();
        if (Platform.OS !== 'web' && !nativeRefresh) {
          await clearAuth();
          return false;
        }
        const result = await api.refresh(nativeRefresh);
        await applyAuth(result);
        return true;
      } catch (next) {
        if (next instanceof AccountApiError && next.status === 401) {
          await clearAuth();
          return false;
        }
        if (next instanceof AccountApiError && next.status === 403 && /verification/i.test(next.message)) {
          setError(next.message);
          return false;
        }
        setError(next instanceof Error ? next.message : String(next));
        return false;
      } finally {
        refreshInFlight.current = null;
      }
    })();
    refreshInFlight.current = attempt;
    return attempt;
  }, [enabled, api, applyAuth, clearAuth]);

  useEffect(() => {
    if (!baseReady || !deploymentReady) return;
    if (!enabled) {
      setReady(true);
      return;
    }
    let active = true;
    void refreshSession().finally(() => {
      if (active) setReady(true);
    });
    return () => { active = false; };
  }, [baseReady, deploymentReady, enabled, refreshSession]);

  useEffect(() => {
    if (!enabled || !accessToken || !accessExpiresAt) return;
    const delay = Math.max(1_000, accessExpiresAt - Date.now() - 60_000);
    const handle = setTimeout(() => { void refreshSession(); }, delay);
    return () => clearTimeout(handle);
  }, [enabled, accessToken, accessExpiresAt, refreshSession]);

  const requireEnabled = useCallback(() => {
    if (!enabled) throw new Error('Accounts are disabled for this deployment.');
  }, [enabled]);

  const requireAccessToken = useCallback((): string => {
    requireEnabled();
    if (!accessToken) throw new Error('Sign in to use this account feature.');
    return accessToken;
  }, [accessToken, requireEnabled]);

  const value = useMemo<AuthContextValue>(() => ({
    ready,
    enabled,
    localOnly,
    emailVerificationRequired,
    user,
    accessToken,
    accountBaseUrl,
    error,
    async setAccountBaseUrl(next) {
      requireEnabled();
      const normalized = normalizeBaseUrl(next);
      setAccountBaseUrlState(normalized);
      await setSetting('account.apiBaseUrl', normalized);
      await clearAuth();
    },
    async signup(email, password, displayName) {
      requireEnabled();
      await applyAuth(await api.signup(email.trim(), password, displayName));
    },
    async login(email, password) {
      requireEnabled();
      await applyAuth(await api.login(email.trim(), password));
    },
    async logout() {
      if (!enabled) return;
      const nativeRefresh = Platform.OS === 'web' ? null : await loadNativeRefreshToken();
      try {
        await api.logout(nativeRefresh);
      } finally {
        await clearAuth();
      }
    },
    async logoutAll() {
      const token = requireAccessToken();
      try {
        await api.logoutAll(token);
      } finally {
        await clearAuth();
      }
    },
    refreshSession,
    async requestEmailVerification(email) {
      requireEnabled();
      await api.requestEmailVerification(email.trim());
    },
    async confirmEmailVerification(token) {
      requireEnabled();
      const verified = await api.confirmEmailVerification(token.trim());
      setUser((current) => current && current.id === verified.id ? verified : current);
      setError('');
      return verified;
    },
    async requestPasswordReset(email) {
      requireEnabled();
      await api.requestPasswordReset(email.trim());
    },
    async confirmPasswordReset(token, newPassword) {
      requireEnabled();
      await api.confirmPasswordReset(token.trim(), newPassword);
      await clearAuth();
    },
    async changePassword(currentPassword, newPassword) {
      await applyAuth(await api.changePassword(currentPassword, newPassword, requireAccessToken()));
    },
    providerCredentials() {
      return api.providerCredentials(requireAccessToken());
    },
    saveProviderCredential(provider, secret, label = 'default') {
      return api.saveProviderCredential(provider, secret, requireAccessToken(), label);
    },
    deleteProviderCredential(provider, label = 'default') {
      return api.deleteProviderCredential(provider, requireAccessToken(), label);
    },
  }), [
    accessToken,
    accountBaseUrl,
    api,
    applyAuth,
    clearAuth,
    emailVerificationRequired,
    enabled,
    error,
    localOnly,
    ready,
    refreshSession,
    requireAccessToken,
    requireEnabled,
    user,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
