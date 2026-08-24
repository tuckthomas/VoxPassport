import { Platform } from 'react-native';

const REFRESH_TOKEN_KEY = 'voxpassport.auth.refreshToken';

export async function loadNativeRefreshToken(): Promise<string | null> {
  if (Platform.OS === 'web') return null;
  const SecureStore = await import('expo-secure-store');
  return SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
}

export async function saveNativeRefreshToken(token: string | null): Promise<void> {
  if (Platform.OS === 'web') return;
  const SecureStore = await import('expo-secure-store');
  if (token) {
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token);
  } else {
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  }
}
