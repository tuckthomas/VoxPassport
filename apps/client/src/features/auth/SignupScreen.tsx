import { useState } from 'react';
import { router, Link } from 'expo-router';
import { Pressable, Text, TextInput } from 'react-native';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useAuth } from '@/auth/AuthContext';
import { colors } from '@/theme';

export default function SignupScreen() {
  const auth = useAuth();
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit() {
    if (busy) return;
    if (!email.trim()) return setError('Enter an email address.');
    if (password.length < 12) return setError('Password must be at least 12 characters.');
    if (password !== confirm) return setError('Passwords do not match.');
    setBusy(true);
    setError('');
    try {
      await auth.signup(email, password, displayName || undefined);
      router.replace('/account');
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Create account" subtitle="Email/password signup. OAuth/social providers can be added later without changing the account model.">
      <Card title="Account details">
        <TextInput
          value={displayName}
          onChangeText={setDisplayName}
          textContentType="name"
          autoComplete="name"
          placeholder="Display name (optional)"
          placeholderTextColor={colors.muted}
          style={inputStyle}
        />
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
          textContentType="newPassword"
          autoComplete="new-password"
          placeholder="Password (12+ characters)"
          placeholderTextColor={colors.muted}
          style={inputStyle}
        />
        <TextInput
          value={confirm}
          onChangeText={setConfirm}
          secureTextEntry
          textContentType="newPassword"
          autoComplete="new-password"
          placeholder="Confirm password"
          placeholderTextColor={colors.muted}
          style={inputStyle}
          onSubmitEditing={() => void submit()}
        />
        {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
        <Pressable disabled={busy} onPress={() => void submit()} style={buttonStyle}>
          <Text style={{ color: colors.text, fontWeight: '700' }}>{busy ? 'Creating…' : 'Create account'}</Text>
        </Pressable>
        <Link href="/login" style={{ color: colors.accent }}>Already have an account? Sign in</Link>
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
