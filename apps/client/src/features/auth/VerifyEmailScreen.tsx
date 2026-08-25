import { useEffect, useMemo, useState } from 'react';
import { Link, Redirect, useLocalSearchParams } from 'expo-router';
import { Pressable, Text, TextInput } from 'react-native';
import { useAuth } from '@/auth/AuthContext';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { colors } from '@/theme';

export default function VerifyEmailScreen() {
  const auth = useAuth();
  const params = useLocalSearchParams<{ token?: string | string[]; email?: string | string[] }>();
  const token = useMemo(() => Array.isArray(params.token) ? params.token[0] ?? '' : params.token ?? '', [params.token]);
  const initialEmail = useMemo(() => Array.isArray(params.email) ? params.email[0] ?? '' : params.email ?? '', [params.email]);
  const [email, setEmail] = useState(initialEmail || auth.user?.email || '');
  const [busy, setBusy] = useState(false);
  const [verified, setVerified] = useState(Boolean(auth.user?.email_verified));
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  if (auth.ready && !auth.enabled) return <Redirect href="/" />;

  async function confirm() {
    if (!token || busy || verified) return;
    setBusy(true);
    setError('');
    try {
      await auth.confirmEmailVerification(token);
      setVerified(true);
      setMessage('Email verified. Your account is ready to use.');
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (token && !verified) void confirm();
    // Run once per token; retry remains available with a new link.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function resend() {
    if (busy || !email.trim()) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await auth.requestEmailVerification(email);
      setMessage('If that account is active and unverified, a new verification link has been sent.');
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Verify email" subtitle="Verification links are one-time and expire automatically.">
      <Card title={verified ? 'Verified' : 'Email verification'}>
        {verified ? (
          <>
            <Text style={{ color: colors.success }}>{message || 'Your email address is verified.'}</Text>
            <Link href="/account" style={{ color: colors.accent }}>Continue to account</Link>
          </>
        ) : (
          <>
            {token && busy ? <Text style={{ color: colors.muted }}>Verifying link…</Text> : null}
            {!token ? <Text style={{ color: colors.muted }}>Enter your email to request a new verification link.</Text> : null}
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
            {message ? <Text style={{ color: colors.success }}>{message}</Text> : null}
            {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
            <Pressable disabled={busy || !email.trim()} onPress={() => void resend()} style={buttonStyle}>
              <Text style={{ color: colors.text, fontWeight: '700' }}>{busy ? 'Working…' : 'Send verification link'}</Text>
            </Pressable>
            <Link href="/login" style={{ color: colors.accent }}>Back to sign in</Link>
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
