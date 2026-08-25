import { useMemo, useState } from 'react';
import { Link, Redirect, useLocalSearchParams } from 'expo-router';
import { Pressable, Text, TextInput } from 'react-native';
import { useAuth } from '@/auth/AuthContext';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { colors } from '@/theme';

export default function ResetPasswordScreen() {
  const auth = useAuth();
  const params = useLocalSearchParams<{ token?: string | string[] }>();
  const token = useMemo(() => Array.isArray(params.token) ? params.token[0] ?? '' : params.token ?? '', [params.token]);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState('');

  if (auth.ready && !auth.enabled) return <Redirect href="/" />;

  async function submit() {
    if (busy) return;
    if (!token) return setError('This reset link is missing its token. Request a new password reset link.');
    if (password.length < 12) return setError('Password must be at least 12 characters.');
    if (password !== confirm) return setError('Passwords do not match.');
    setBusy(true);
    setError('');
    try {
      await auth.confirmPasswordReset(token, password);
      setPassword('');
      setConfirm('');
      setComplete(true);
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Choose a new password" subtitle="The reset token is one-time and expires automatically.">
      <Card title={complete ? 'Password changed' : 'New password'}>
        {complete ? (
          <>
            <Text style={{ color: colors.success }}>
              Your password was reset and existing signed-in sessions were revoked.
            </Text>
            <Link href="/login" style={{ color: colors.accent }}>Sign in with the new password</Link>
          </>
        ) : (
          <>
            {!token ? <Text style={{ color: colors.warning }}>No reset token was supplied.</Text> : null}
            <TextInput
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              textContentType="newPassword"
              autoComplete="new-password"
              placeholder="New password (12+ characters)"
              placeholderTextColor={colors.muted}
              style={inputStyle}
            />
            <TextInput
              value={confirm}
              onChangeText={setConfirm}
              secureTextEntry
              textContentType="newPassword"
              autoComplete="new-password"
              placeholder="Confirm new password"
              placeholderTextColor={colors.muted}
              style={inputStyle}
              onSubmitEditing={() => void submit()}
            />
            {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
            <Pressable disabled={busy || !token} onPress={() => void submit()} style={buttonStyle}>
              <Text style={{ color: colors.text, fontWeight: '700' }}>{busy ? 'Resetting…' : 'Reset password'}</Text>
            </Pressable>
            <Link href="/forgot-password" style={{ color: colors.accent }}>Request another reset link</Link>
          </>
        )}
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
