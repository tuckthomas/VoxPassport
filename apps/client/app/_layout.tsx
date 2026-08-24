import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { AuthProvider } from '@/auth/AuthContext';
import { RuntimeTargetProvider } from '@/config/RuntimeTargetContext';

export default function RootLayout() {
  return (
    <RuntimeTargetProvider>
      <AuthProvider>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: '#0b1020' },
            headerTintColor: '#f8fafc',
            contentStyle: { backgroundColor: '#090d16' },
          }}
        >
          <Stack.Screen name="index" options={{ title: 'VoxPassport' }} />
          <Stack.Screen name="translator" options={{ title: 'Translator' }} />
          <Stack.Screen name="models" options={{ title: 'Models & Engines' }} />
          <Stack.Screen name="voice-profiles" options={{ title: 'Voice Profiles' }} />
          <Stack.Screen name="runtime" options={{ title: 'Runtime & Audio' }} />
          <Stack.Screen name="settings" options={{ title: 'Settings' }} />
          <Stack.Screen name="account" options={{ title: 'Account' }} />
          <Stack.Screen name="login" options={{ title: 'Sign in' }} />
          <Stack.Screen name="signup" options={{ title: 'Create account' }} />
        </Stack>
      </AuthProvider>
    </RuntimeTargetProvider>
  );
}
