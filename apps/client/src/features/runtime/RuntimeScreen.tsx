import { useEffect, useState } from 'react';
import { Pressable, Text } from 'react-native';
import type { RuntimeStatus } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { colors } from '@/theme';

export default function RuntimeScreen() {
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [error, setError] = useState('');

  async function refresh() {
    setError('');
    try {
      setRuntime(await api.status());
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    }
  }

  useEffect(() => {
    if (target.ready) void refresh();
  }, [target.ready, api]);

  return (
    <Screen
      title="Runtime & Audio"
      subtitle="Expo client diagnostics. Model/runtime ownership remains in the VoxPassport local or self-hosted runtime."
      action={<RefreshButton onPress={() => void refresh()} />}
    >
      <Card title="Runtime target" subtitle={`${target.mode} · ${target.activeBaseUrl}`}>
        <StatusLine label="Runtime" value={runtime?.status ?? 'unavailable'} />
        <StatusLine label="Pipeline mode" value={runtime?.mode ?? 'unknown'} />
        <StatusLine label="TTS mode" value={runtime?.tts_mode ?? 'unknown'} />
        <StatusLine label="Languages" value={runtime ? `${runtime.user_language} ↔ ${runtime.remote_language}` : 'unknown'} />
        <StatusLine label="Model residency" value={runtime?.model_residency ?? 'unknown'} />
        <StatusLine label="Models loaded" value={runtime ? (runtime.models_loaded ? 'yes' : 'no') : 'unknown'} />
      </Card>

      <Card
        title="Desktop audio boundary"
        subtitle="System audio integration is a runtime/native-audio responsibility, not a second desktop UI shell."
      >
        <Text style={{ color: colors.muted }}>
          The Expo client will consume audio-device and routing state through stable runtime APIs. Windows microphone capture,
          WASAPI loopback, and virtual-microphone output remain native/runtime capabilities and must not be implemented by
          embedding the Expo UI inside another application framework.
        </Text>
      </Card>

      {runtime ? (
        <Card title="Active model slots">
          {Object.entries(runtime.active_slots ?? {}).map(([slot, model]) => (
            <StatusLine key={slot} label={slot} value={model || 'none'} />
          ))}
          {!Object.keys(runtime.active_slots ?? {}).length ? (
            <Text style={{ color: colors.muted }}>No active slots reported.</Text>
          ) : null}
        </Card>
      ) : null}

      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <Text style={{ color: colors.muted }}>
      <Text style={{ color: colors.text, fontWeight: '600' }}>{label}: </Text>
      {value}
    </Text>
  );
}

function RefreshButton({ onPress }: { onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={{ borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 }}
    >
      <Text style={{ color: colors.text }}>Refresh</Text>
    </Pressable>
  );
}
