import { useEffect, useMemo, useState } from 'react';
import { Text } from 'react-native';
import { ActionButton, Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { VoxPassportApi } from '@/api/client';
import type { ModelEntry } from '@/api/contracts';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { colors } from '@/theme';

export default function ModelsScreen() {
  const target = useRuntimeTarget();
  const api = useMemo(
    () => new VoxPassportApi(target.activeBaseUrl, { nativeLocal: target.mode === 'local' }),
    [target.activeBaseUrl, target.mode],
  );
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [error, setError] = useState('');

  async function refresh() {
    setError('');
    try {
      setModels(await api.models());
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    }
  }

  useEffect(() => {
    if (target.ready) void refresh();
  }, [target.ready, api]);

  return (
    <Screen
      title="Models & Engines"
      subtitle={`Catalog from ${target.mode}: ${target.activeBaseUrl}`}
      action={<ActionButton label="Refresh" onPress={() => void refresh()} />}
    >
      {models.map((model) => (
        <Card
          key={model.model_id}
          title={model.name || model.model_id}
          subtitle={`${model.capability}${model.provider ? ` · ${model.provider}` : ''}`}
        >
          <Text style={{ color: colors.muted }}>{model.model_id}</Text>
          <Text style={{ color: colors.muted }}>
            Install state: {model.installation_status ?? 'unknown'}
          </Text>
          {model.required_runtime ? (
            <Text style={{ color: colors.muted }}>Runtime: {model.required_runtime}</Text>
          ) : null}
        </Card>
      ))}
      {!models.length && !error ? (
        <Text style={{ color: colors.muted }}>No model catalog loaded yet.</Text>
      ) : null}
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}
