import { useState } from 'react';
import { Link, Redirect } from 'expo-router';
import { Pressable, Text, TextInput, View } from 'react-native';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useAuth } from '@/auth/AuthContext';
import { colors } from '@/theme';

export default function AccountScreen() {
  const auth = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  if (!auth.ready) {
    return <Screen title="Account"><Text style={{ color: colors.muted }}>Checking account configuration…</Text></Screen>;
  }

  if (!auth.enabled) return <Redirect href="/" />;

  if (!auth.user) {
    return (
      <Screen title="Account" subtitle="Accounts are enabled for this deployment, but local/private inference remains independent of account identity.">
        <Card title="Not signed in">
          {auth.error ? <Text style={{ color: colors.warning }}>{auth.error}</Text> : null}
          <View style={{ flexDirection: 'row', gap: 14, flexWrap: 'wrap' }}>
            <Link href="/login" style={{ color: colors.accent }}>Sign in</Link>
            <Link href="/signup" style={{ color: colors.accent }}>Create account</Link>
          </View>
        </Card>
      </Screen>
    );
  }

  async function changePassword() {
    if (busy) return;
    if (newPassword.length < 12) return setError('New password must be at least 12 characters.');
    if (newPassword !== confirmPassword) return setError('New passwords do not match.');
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await auth.changePassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setMessage('Password changed. Other sessions were revoked.');
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Account" subtitle="Account identity is separate from the local inference runtime.">
      <Card title={auth.user.display_name || auth.user.email} subtitle={auth.user.email}>
        <Text style={{ color: colors.muted }}>Account ID: {auth.user.id}</Text>
        <View style={{ flexDirection: 'row', gap: 10, flexWrap: 'wrap' }}>
          <Pressable onPress={() => void auth.logout()} style={buttonStyle}>
            <Text style={{ color: colors.text }}>Sign out here</Text>
          </Pressable>
          <Pressable onPress={() => void auth.logoutAll()} style={buttonStyle}>
            <Text style={{ color: colors.text }}>Sign out everywhere</Text>
          </Pressable>
        </View>
      </Card>

      <Card title="Change password" subtitle="Changing the password revokes all existing refresh sessions and issues a new session to this client.">
        <TextInput
          value={currentPassword}
          onChangeText={setCurrentPassword}
          secureTextEntry
          autoComplete="current-password"
          textContentType="password"
          placeholder="Current password"
          placeholderTextColor={colors.muted}
          style={inputStyle}
        />
        <TextInput
          value={newPassword}
          onChangeText={setNewPassword}
          secureTextEntry
          autoComplete="new-password"
          textContentType="newPassword"
          placeholder="New password (12+ characters)"
          placeholderTextColor={colors.muted}
          style={inputStyle}
        />
        <TextInput
          value={confirmPassword}
          onChangeText={setConfirmPassword}
          secureTextEntry
          autoComplete="new-password"
          textContentType="newPassword"
          placeholder="Confirm new password"
          placeholderTextColor={colors.muted}
          style={inputStyle}
        />
        {message ? <Text style={{ color: colors.success }}>{message}</Text> : null}
        {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
        <Pressable disabled={busy} onPress={() => void changePassword()} style={buttonStyle}>
          <Text style={{ color: colors.text }}>{busy ? 'Changing…' : 'Change password'}</Text>
        </Pressable>
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
  borderColor: colors.border,
  borderRadius: 8,
  paddingHorizontal: 12,
  paddingVertical: 9,
} as const;
