import { Platform } from 'react-native';

const PREFIX = 'voxpassport.';

export async function getSetting(key: string): Promise<string | null> {
  const namespaced = PREFIX + key;
  if (Platform.OS === 'web') {
    if (typeof globalThis.localStorage === 'undefined') return null;
    return globalThis.localStorage.getItem(namespaced);
  }
  const SecureStore = await import('expo-secure-store');
  return SecureStore.getItemAsync(namespaced);
}

export async function setSetting(key: string, value: string): Promise<void> {
  const namespaced = PREFIX + key;
  if (Platform.OS === 'web') {
    if (typeof globalThis.localStorage !== 'undefined') globalThis.localStorage.setItem(namespaced, value);
    return;
  }
  const SecureStore = await import('expo-secure-store');
  await SecureStore.setItemAsync(namespaced, value);
}

export async function deleteSetting(key: string): Promise<void> {
  const namespaced = PREFIX + key;
  if (Platform.OS === 'web') {
    if (typeof globalThis.localStorage !== 'undefined') globalThis.localStorage.removeItem(namespaced);
    return;
  }
  const SecureStore = await import('expo-secure-store');
  await SecureStore.deleteItemAsync(namespaced);
}
