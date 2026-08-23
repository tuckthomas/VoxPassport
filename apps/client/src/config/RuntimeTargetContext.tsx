import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react';
import { getSetting, setSetting } from '@/storage/settingsStorage';

export type RuntimeMode = 'local' | 'cloud';

export type RuntimeTarget = {
  mode: RuntimeMode;
  localBaseUrl: string;
  cloudBaseUrl: string;
};

type RuntimeTargetContextValue = RuntimeTarget & {
  ready: boolean;
  setMode: (mode: RuntimeMode) => Promise<void>;
  setLocalBaseUrl: (url: string) => Promise<void>;
  setCloudBaseUrl: (url: string) => Promise<void>;
};

const DEFAULT_LOCAL_URL = 'http://127.0.0.1:8766';
const DEFAULT_CLOUD_URL = 'https://api.voxpassport.com';

const RuntimeTargetContext = createContext<RuntimeTargetContextValue | null>(null);

function normalizeBaseUrl(value: string, fallback: string): string {
  const normalized = value.trim().replace(/\/+$/, '');
  return normalized || fallback;
}

export function RuntimeTargetProvider({ children }: PropsWithChildren) {
  const [mode, setModeState] = useState<RuntimeMode>('local');
  const [localBaseUrl, setLocalBaseUrlState] = useState(DEFAULT_LOCAL_URL);
  const [cloudBaseUrl, setCloudBaseUrlState] = useState(DEFAULT_CLOUD_URL);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([
      getSetting('runtime.mode'),
      getSetting('runtime.localBaseUrl'),
      getSetting('runtime.cloudBaseUrl'),
    ]).then(([savedMode, savedLocal, savedCloud]) => {
      if (!active) return;
      if (savedMode === 'local' || savedMode === 'cloud') setModeState(savedMode);
      if (savedLocal) setLocalBaseUrlState(normalizeBaseUrl(savedLocal, DEFAULT_LOCAL_URL));
      if (savedCloud) setCloudBaseUrlState(normalizeBaseUrl(savedCloud, DEFAULT_CLOUD_URL));
      setReady(true);
    }).catch(() => setReady(true));
    return () => { active = false; };
  }, []);

  const value = useMemo<RuntimeTargetContextValue>(() => ({
    mode,
    localBaseUrl,
    cloudBaseUrl,
    ready,
    async setMode(next) {
      setModeState(next);
      await setSetting('runtime.mode', next);
    },
    async setLocalBaseUrl(next) {
      const value = normalizeBaseUrl(next, DEFAULT_LOCAL_URL);
      setLocalBaseUrlState(value);
      await setSetting('runtime.localBaseUrl', value);
    },
    async setCloudBaseUrl(next) {
      const value = normalizeBaseUrl(next, DEFAULT_CLOUD_URL);
      setCloudBaseUrlState(value);
      await setSetting('runtime.cloudBaseUrl', value);
    },
  }), [mode, localBaseUrl, cloudBaseUrl, ready]);

  return <RuntimeTargetContext.Provider value={value}>{children}</RuntimeTargetContext.Provider>;
}

export function useRuntimeTarget(): RuntimeTargetContextValue {
  const value = useContext(RuntimeTargetContext);
  if (!value) throw new Error('useRuntimeTarget must be used inside RuntimeTargetProvider');
  return value;
}
