import { useEffect, useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget, type RuntimeMode } from '@/config/RuntimeTargetContext';
import { colors, theme } from '@/theme';

export default function SettingsScreen() {
  const target = useRuntimeTarget();
  const [localUrl, setLocalUrl] = useState(target.localBaseUrl);
  const [selfHostedUrl, setSelfHostedUrl] = useState(target.selfHostedBaseUrl);

  useEffect(() => setLocalUrl(target.localBaseUrl), [target.localBaseUrl]);
  useEffect(() => setSelfHostedUrl(target.selfHostedBaseUrl), [target.selfHostedBaseUrl]);

  return (
    <Screen title="Settings" subtitle="Local runtime is the desktop default. Managed cloud remains optional.">
      <Card title="Processing target">
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
          <ModeButton label="Local" value="local" selected={target.mode} onSelect={target.setMode} />
          <ModeButton label="Self-hosted" value="self_hosted" selected={target.mode} onSelect={target.setMode} />
          <ModeButton label="Cloud (future)" value="cloud" selected={target.mode} onSelect={target.setMode} />
        </View>
      </Card>
      <Card title="Local runtime URL">
        <TextInput value={localUrl} onChangeText={setLocalUrl} autoCapitalize="none" style={inputStyle} />
        <Pressable onPress={() => void target.setLocalBaseUrl(localUrl)} style={buttonStyle}><Text style={{ color: colors.text }}>Save local URL</Text></Pressable>
      </Card>
      <Card title="Self-hosted runtime URL">
        <TextInput value={selfHostedUrl} onChangeText={setSelfHostedUrl} autoCapitalize="none" style={inputStyle} />
        <Pressable onPress={() => void target.setSelfHostedBaseUrl(selfHostedUrl)} style={buttonStyle}><Text style={{ color: colors.text }}>Save self-hosted URL</Text></Pressable>
      </Card>
    </Screen>
  );
}

function ModeButton({ label, value, selected, onSelect }: { label: string; value: RuntimeMode; selected: RuntimeMode; onSelect: (value: RuntimeMode) => Promise<void> }) {
  return (
    <Pressable onPress={() => void onSelect(value)} style={[buttonStyle, selected === value && { borderColor: colors.accent, backgroundColor: theme.colors.surfaceRaised }]}>
      <Text style={{ color: colors.text }}>{label}</Text>
    </Pressable>
  );
}

const inputStyle = { color: colors.text, borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10 } as const;
const buttonStyle = { alignSelf: 'flex-start' as const, borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 9 };
