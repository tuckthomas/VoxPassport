import { useState } from 'react';
import { Redirect, router, Link } from 'expo-router';
import { Text, TextInput } from 'react-native';
import { Card } from '@/components/Card';
import { RaisedButton } from '@/components/RaisedButton';
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

  if (auth.ready && !auth.enabled) return <Redirect href="/" />;

  async function submit() {
    if (busy) return;
    if (!email.trim()) return setError('Enter an email address.');
    if (password.length < 12) return setError('Password must be at least 12 characters.');
    if (password !== confirm) return setError('Passwords do not match.');
    setBusy(true);
    setError('');
    try {
      await auth.signup(email, password, displayName || undefined);
      if (auth.emailVerificationRequired) {
        router.replace({ pathname: '/verify-email', params: { email: email.trim() } });
      } else {
        router.replace('/account');
      }
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
        <Text style={{ color: colors.muted }}>
          {auth.emailVerificationRequired
            ? 'This deployment requires email verification before account-backed features can be used.'
            : 'A verification link is issued at signup, but this deployment does not require verification before sign-in.'}
        </Text>
        {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
        <RaisedButton label={busy ? 'Creating…' : 'Create account'} disabled={busy} onPress={() => void submit()} />
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
