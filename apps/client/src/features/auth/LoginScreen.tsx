import { useState } from 'react';
import { Redirect, router, Link } from 'expo-router';
import { Text, TextInput, View } from 'react-native';
import { Card } from '@/components/Card';
import { RaisedButton } from '@/components/RaisedButton';
import { Screen } from '@/components/Screen';
import { useAuth } from '@/auth/AuthContext';
import { colors } from '@/theme';

export default function LoginScreen() {
  const auth = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  if (auth.ready && !auth.enabled) return <Redirect href="/" />;

  async function submit() {
    if (busy || !email.trim() || !password) return;
    setBusy(true);
    setError('');
    try {
      await auth.login(email, password);
      router.replace('/account');
    } catch (next) {
      const message = next instanceof Error ? next.message : String(next);
      setError(message);
      if (/email verification required/i.test(message)) {
        router.push({ pathname: '/verify-email', params: { email: email.trim() } });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Sign in" subtitle="Email/password authentication. Social sign-in is intentionally not enabled yet.">
      <Card title="VoxPassport account">
        <TextInput
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          textContentType="emailAddress"
          autoComplete="email"
          placeholder="Email"
          placeholderTextColor={colors.muted}
          style={inputStyle}
        />
        <TextInput
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          textContentType="password"
          autoComplete="current-password"
          placeholder="Password"
          placeholderTextColor={colors.muted}
          style={inputStyle}
          onSubmitEditing={() => void submit()}
        />
        {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
        <RaisedButton label={busy ? 'Signing in…' : 'Sign in'} disabled={busy} onPress={() => void submit()} />
        <View style={{ gap: 8 }}>
          <Link href="/forgot-password" style={{ color: colors.accent }}>Forgot password?</Link>
          <Link href="/signup" style={{ color: colors.accent }}>Create an account</Link>
        </View>
      </Card>
    </Screen>
  );
}

const inputStyle = {
  color: colors.text,
  borderWidth: 1,
  borderColor: colors.border,
  borderRadius: 8,
  paddingHorizontal: 12,
  paddingVertical: 10,
} as const;

const buttonStyle = {
  alignSelf: 'flex-start' as const,
  borderWidth: 1,
  borderColor: colors.accent,
  borderRadius: 8,
  paddingHorizontal: 16,
  paddingVertical: 10,
} as const;
