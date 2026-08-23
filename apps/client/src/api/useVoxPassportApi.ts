import { useMemo } from 'react';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { VoxPassportApi } from './client';

/** Return the API client for the currently selected Expo runtime target. */
export function useVoxPassportApi(): VoxPassportApi {
  const target = useRuntimeTarget();
  return useMemo(
    () => new VoxPassportApi(target.activeBaseUrl),
    [target.activeBaseUrl],
  );
}
