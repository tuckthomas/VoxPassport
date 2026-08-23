import { useMemo } from 'react';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { VoxPassportApi } from './client';

/**
 * Return the API client for the currently selected runtime target.
 *
 * Feature modules intentionally do not decide whether requests travel through
 * browser fetch, the Tauri loopback bridge, or a future authenticated transport.
 */
export function useVoxPassportApi(): VoxPassportApi {
  const target = useRuntimeTarget();
  return useMemo(
    () => new VoxPassportApi(target.activeBaseUrl, { nativeLocal: target.mode === 'local' }),
    [target.activeBaseUrl, target.mode],
  );
}
