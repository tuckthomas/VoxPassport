import { useEffect, useState } from 'react';
import { Link } from 'expo-router';
import { Pressable, Text, TextInput, View } from 'react-native';
import type { ProviderCredentialSummary } from '@/auth/contracts';
import { useAuth } from '@/auth/AuthContext';
import { Card } from '@/components/Card';
import { RaisedButton } from '@/components/RaisedButton';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget, type RuntimeMode } from '@/config/RuntimeTargetContext';
import { colors, theme } from '@/theme';

export default function SettingsScreen() {
  const target = useRuntimeTarget();
  const auth = useAuth();
  const [localUrl, setLocalUrl] = useState(target.localBaseUrl);
  const [selfHostedUrl, setSelfHostedUrl] = useState(target.selfHostedBaseUrl);
  const [accountUrl, setAccountUrl] = useState(auth.accountBaseUrl);
  const [provider, setProvider] = useState('google');
  const [providerSecret, setProviderSecret] = useState('');
  const [credentials, setCredentials] = useState<ProviderCredentialSummary[]>([]);
  const [credentialBusy, setCredentialBusy] = useState(false);
  const [credentialError, setCredentialError] = useState('');
  const [credentialMessage, setCredentialMessage] = useState('');

  useEffect(() => setLocalUrl(target.localBaseUrl), [target.localBaseUrl]);
  useEffect(() => setSelfHostedUrl(target.selfHostedBaseUrl), [target.selfHostedBaseUrl]);
  useEffect(() => setAccountUrl(auth.accountBaseUrl), [auth.accountBaseUrl]);

  async function reloadCredentials() {
    if (!auth.enabled || !auth.user) {
      setCredentials([]);
      return;
    }
    try {
      setCredentials(await auth.providerCredentials());
    } catch (next) {
      setCredentialError(next instanceof Error ? next.message : String(next));
    }
  }

  useEffect(() => {
    void reloadCredentials();
  }, [auth.enabled, auth.user?.id, auth.accessToken]);

  async function saveCredential() {
    if (!provider.trim() || !providerSecret || credentialBusy) return;
    setCredentialBusy(true);
    setCredentialError('');
    setCredentialMessage('');
    try {
      await auth.saveProviderCredential(provider.trim().toLowerCase(), providerSecret);
      setProviderSecret('');
      setCredentialMessage('Credential encrypted and saved. The secret will not be displayed again.');
      await reloadCredentials();
    } catch (next) {
      setCredentialError(next instanceof Error ? next.message : String(next));
    } finally {
      setCredentialBusy(false);
    }
  }

  async function removeCredential(item: ProviderCredentialSummary) {
    setCredentialBusy(true);
    setCredentialError('');
    setCredentialMessage('');
    try {
      await auth.deleteProviderCredential(item.provider, item.label);
      await reloadCredentials();
    } catch (next) {
      setCredentialError(next instanceof Error ? next.message : String(next));
    } finally {
      setCredentialBusy(false);
    }
  }

  return (
    <Screen title="Settings" subtitle={auth.localOnly ? 'Single-user local deployment.' : 'Local runtime is the desktop default. Managed cloud remains optional.'}>
      {auth.localOnly ? (
        <Card title="Deployment mode" subtitle="Configured by VOXPASSPORT_LOCAL_ONLY or deployment JSON.">
          <Text style={{ color: colors.success }}>Local-only · accounts disabled</Text>
          <Text style={{ color: colors.muted }}>
            Login, signup, account sessions, account credential vaults, and multi-user abuse controls are not used by this deployment.
          </Text>
        </Card>
      ) : null}

      <Card title="Processing target">
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
          <ModeButton label="Local" value="local" selected={target.mode} onSelect={target.setMode} />
          <ModeButton label="Self-hosted" value="self_hosted" selected={target.mode} onSelect={target.setMode} />
          <ModeButton label="Cloud (future)" value="cloud" selected={target.mode} onSelect={target.setMode} />
        </View>
      </Card>
      <Card title="Local runtime URL">
        <TextInput value={localUrl} onChangeText={setLocalUrl} autoCapitalize="none" style={inputStyle} />
        <RaisedButton label="Save local URL" onPress={() => void target.setLocalBaseUrl(localUrl)} />
      </Card>
      <Card title="Self-hosted runtime URL">
        <TextInput value={selfHostedUrl} onChangeText={setSelfHostedUrl} autoCapitalize="none" style={inputStyle} />
        <RaisedButton label="Save self-hosted URL" onPress={() => void target.setSelfHostedBaseUrl(selfHostedUrl)} />
      </Card>

      {auth.enabled ? (
        <>
          <Card title="Account service URL" subtitle="Separate from inference so local/private use does not require an account.">
            <TextInput value={accountUrl} onChangeText={setAccountUrl} autoCapitalize="none" style={inputStyle} />
            <RaisedButton label="Save account URL" onPress={() => void auth.setAccountBaseUrl(accountUrl)} />
          </Card>

          <Card title="Provider credential vault" subtitle="Provider secrets are encrypted by the account service and are never returned by list APIs.">
            {!auth.user ? (
              <Text style={{ color: colors.muted }}>
                <Link href="/login" style={{ color: colors.accent }}>Sign in</Link> to store provider credentials for account/cloud use.
              </Text>
            ) : (
              <>
                <TextInput
                  value={provider}
                  onChangeText={setProvider}
                  autoCapitalize="none"
                  autoCorrect={false}
                  placeholder="Provider, e.g. google"
                  placeholderTextColor={colors.muted}
                  style={inputStyle}
                />
                <TextInput
                  value={providerSecret}
                  onChangeText={setProviderSecret}
                  secureTextEntry
                  autoCapitalize="none"
                  autoCorrect={false}
                  placeholder="API key / provider secret"
                  placeholderTextColor={colors.muted}
                  style={inputStyle}
                />
                <RaisedButton label={credentialBusy ? 'Saving…' : 'Encrypt & save credential'} disabled={credentialBusy || !providerSecret} onPress={() => void saveCredential()} />
                {credentialMessage ? <Text style={{ color: colors.success }}>{credentialMessage}</Text> : null}
                {credentialError ? <Text style={{ color: colors.danger }}>{credentialError}</Text> : null}
                {credentials.length ? credentials.map((item) => (
                  <View key={item.id} style={{ borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 10, gap: 6 }}>
                    <Text style={{ color: colors.text, fontWeight: '700' }}>{item.provider} · {item.label}</Text>
                    <Text style={{ color: colors.muted }}>Encrypted credential · key version {item.key_version}</Text>
                    <RaisedButton label="Delete" backgroundColor="#b23b42" disabled={credentialBusy} onPress={() => void removeCredential(item)} />
                  </View>
                )) : <Text style={{ color: colors.muted }}>No account-scoped provider credentials saved.</Text>}
              </>
            )}
          </Card>
        </>
      ) : (
        <Card title="Local provider credentials">
          <Text style={{ color: colors.muted }}>
            Account-backed credential storage is disabled. BYO provider adapters use deployment/runtime secrets such as GEMINI_API_KEY; no account database is required.
          </Text>
        </Card>
      )}
    </Screen>
  );
}

function ModeButton({
  label,
  value,
  selected,
  onSelect,
}: {
  label: string;
  value: RuntimeMode;
  selected: RuntimeMode;
  onSelect: (value: RuntimeMode) => Promise<void>;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: selected === value }}
      onPress={() => void onSelect(value)}
      style={[
        buttonStyle,
        selected === value && {
          borderColor: colors.accent,
          backgroundColor: theme.colors.surfaceRaised,
        },
      ]}
    >
      <Text style={{ color: colors.text }}>{label}</Text>
    </Pressable>
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
};
