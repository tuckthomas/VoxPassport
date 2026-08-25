import { useEffect, useMemo, useState } from 'react';
import { Text, View } from 'react-native';
import type { ModelEntry, ModelInstallProgress } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { ActionButton, Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { colors } from '@/theme';

const ACTIVE_CAPABILITIES = new Set(['ASR', 'TRANSLATION', 'TTS', 'VAD']);

export default function ModelsScreen() {
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [progress, setProgress] = useState<Record<string, ModelInstallProgress>>({});
  const [busyModel, setBusyModel] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const downloading = useMemo(
    () => models.filter((model) => ['downloading', 'installing'].includes(model.installation_status ?? '')).map((model) => model.model_id),
    [models],
  );

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

  useEffect(() => {
    if (!downloading.length) return;
    let cancelled = false;
    async function poll() {
      try {
        const entries = await Promise.all(downloading.map(async (modelId) => [modelId, await api.modelInstallProgress(modelId)] as const));
        if (cancelled) return;
        setProgress((current) => ({ ...current, ...Object.fromEntries(entries) }));
        if (entries.some(([, item]) => item.phase === 'done' || item.phase === 'failed')) await refresh();
      } catch (next) {
        if (!cancelled) setError(next instanceof Error ? next.message : String(next));
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 1200);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [downloading.join('|'), api]);

  async function install(model: ModelEntry) {
    setBusyModel(model.model_id);
    setError('');
    setMessage('');
    try {
      const result = await api.installModel(model.model_id, model.upstream_id, model.revision);
      if (!result.success) throw new Error(result.error || 'Model installation did not start.');
      setMessage(`Installation started for ${model.name || model.model_id}.`);
      await refresh();
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusyModel('');
    }
  }

  async function activate(model: ModelEntry) {
    setBusyModel(model.model_id);
    setError('');
    setMessage('');
    try {
      const result = await api.activateModel(model.capability, model.model_id);
      if (!result.success) throw new Error(result.error || 'Model activation failed.');
      setMessage(`${model.name || model.model_id} is now active for ${model.capability}.`);
      await refresh();
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusyModel('');
    }
  }

  async function uninstall(model: ModelEntry) {
    setBusyModel(model.model_id);
    setError('');
    setMessage('');
    try {
      const result = await api.uninstallModel(model.model_id);
      if (!result.success) throw new Error(result.error || 'Model uninstall failed.');
      setMessage(`${model.name || model.model_id} was uninstalled.`);
      await refresh();
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusyModel('');
    }
  }

  return (
    <Screen
      title="Models & Engines"
      subtitle={`Catalog from ${target.mode}: ${target.activeBaseUrl}`}
      action={<ActionButton label="Refresh" onPress={() => void refresh()} />}
    >
      {models.map((model) => {
        const state = model.installation_status ?? 'unknown';
        const itemProgress = progress[model.model_id];
        const isBusy = busyModel === model.model_id;
        const canInstall = model.installable === true;
        const canActivate = state === 'installed' && ACTIVE_CAPABILITIES.has(model.capability) && !model.is_active;
        const canUninstall = state === 'installed' && !model.is_active && !model.is_pinned;
        return (
          <Card
            key={model.model_id}
            title={model.name || model.model_id}
            subtitle={`${model.capability}${model.provider ? ` · ${model.provider}` : ''}${model.is_active ? ' · ACTIVE' : ''}`}
          >
            <Text style={{ color: colors.muted }}>{model.model_id}</Text>
            <Text style={{ color: colors.muted }}>Install state: {state}</Text>
            {itemProgress && ['downloading', 'installing'].includes(itemProgress.phase) ? (
              <Text style={{ color: colors.muted }}>
                Progress: {Math.max(0, Math.min(100, itemProgress.percent ?? 0)).toFixed(1)}% · {itemProgress.phase}
              </Text>
            ) : null}
            {itemProgress?.error ? <Text style={{ color: colors.danger }}>{itemProgress.error}</Text> : null}
            {model.required_runtime ? <Text style={{ color: colors.muted }}>Runtime: {model.required_runtime}</Text> : null}
            {!canInstall && state !== 'installed' && model.installation_reason ? (
              <Text style={{ color: colors.muted }}>{model.installation_reason}</Text>
            ) : null}
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
              {canInstall ? <ActionButton label={isBusy ? 'Starting…' : 'Install'} disabled={isBusy} onPress={() => void install(model)} /> : null}
              {canActivate ? <ActionButton label={isBusy ? 'Activating…' : 'Activate'} disabled={isBusy} onPress={() => void activate(model)} /> : null}
              {canUninstall ? <ActionButton label={isBusy ? 'Removing…' : 'Uninstall'} destructive disabled={isBusy} onPress={() => void uninstall(model)} /> : null}
            </View>
          </Card>
        );
      })}
      {!models.length && !error ? <Text style={{ color: colors.muted }}>No model catalog loaded yet.</Text> : null}
      {message ? <Text style={{ color: colors.success }}>{message}</Text> : null}
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}
