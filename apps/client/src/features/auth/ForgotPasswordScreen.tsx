import { useState } from 'react';
import { Link, Redirect } from 'expo-router';
import { Text, TextInput } from 'react-native';
import { useAuth } from '@/auth/AuthContext';
import { Card } from '@/components/Card';
import { RaisedButton } from '@/components/RaisedButton';
import { Screen } from '@/components/Screen';
import { colors } from '@/theme';

export default function ForgotPasswordScreen() {
  const auth = useAuth();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  if (auth.ready && !auth.enabled) return <Redirect href="/" />;

  async function submit() {
    if (busy || !email.trim()) return;
    setBusy(true);
    setError('');
    try {
      await auth.requestPasswordReset(email);
      setSent(true);
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Reset password" subtitle="Request a one-time password reset link.">
      <Card title="Email address">
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
          onSubmitEditing={() => void submit()}
        />
        {sent ? (
          <Text style={{ color: colors.success }}>
            If an active account exists for that address, a reset link has been sent.
          </Text>
        ) : null}
        {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
        <RaisedButton label={busy ? 'Sending…' : 'Send reset link'} disabled={busy || !email.trim()} onPress={() => void submit()} />
        <Link href="/login" style={{ color: colors.accent }}>Back to sign in</Link>
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
