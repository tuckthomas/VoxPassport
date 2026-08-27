import { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, useWindowDimensions, View } from 'react-native';
import type { ModelEntry, ModelInstallProgress } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { ActionButton } from '@/components/Card';
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
  const [tab, setTab] = useState<'active' | 'hub'>('active');
  const [query, setQuery] = useState('');
  const [capability, setCapability] = useState('ALL');
  const { width } = useWindowDimensions();

  const downloading = useMemo(
    () => models.filter((model) => ['downloading', 'installing'].includes(model.installation_status ?? '')).map((model) => model.model_id),
    [models],
  );

  const visibleModels = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return models.filter((model) => {
      if (tab === 'active' && !model.is_active && model.installation_status !== 'installed') return false;
      if (capability !== 'ALL' && model.capability !== capability) return false;
      if (!needle) return true;
      return [model.name, model.model_id, model.provider, model.upstream_id].some((value) => value?.toLowerCase().includes(needle));
    });
  }, [models, tab, capability, query]);

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
      title="Model Settings"
      subtitle="Manage active speech engines and discover compatible models."
    >
      <View style={styles.panel}>
        <View style={styles.tabs}>
          <Pressable onPress={() => setTab('active')} style={[styles.tab, tab === 'active' && styles.tabActive]}>
            <Text style={[styles.tabText, tab === 'active' && styles.tabTextActive]}>▣  Active Engines</Text>
          </Pressable>
          <Pressable onPress={() => setTab('hub')} style={[styles.tab, tab === 'hub' && styles.tabActive]}>
            <Text style={[styles.tabText, tab === 'hub' && styles.tabTextActive]}>⇩  Hugging Face Hub</Text>
          </Pressable>
        </View>

        <View style={styles.panelHeading}>
          <View style={styles.headingCopy}>
            <View style={styles.headingLine}>
              <Text style={styles.panelTitle}>{tab === 'active' ? 'Active Speech Engines' : 'Hugging Face Model Discovery Hub'}</Text>
              <Text style={styles.repositoryBadge}>{tab === 'active' ? 'LOCAL RUNTIME' : 'HUGGING FACE REPOSITORY'}</Text>
            </View>
            <Text style={styles.panelSubtitle}>
              {tab === 'active'
                ? 'Models installed locally and ready for real-time translation.'
                : 'Download, benchmark, and register open-weights models directly from Hugging Face.'}
            </Text>
          </View>
          <Text style={styles.hardwareBadge}>▣ RTX 2070 (8 GB VRAM) · Ryzen 7 3800X · 32 GB RAM</Text>
        </View>

        <View style={styles.discovery}>
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="⌕  Search models by name, provider, or repository ID…"
            placeholderTextColor="#6f7d91"
            style={styles.search}
          />
          <View style={styles.filters}>
            {['ALL', 'TTS', 'ASR', 'TRANSLATION', 'VAD'].map((item) => (
              <Pressable key={item} onPress={() => setCapability(item)} style={[styles.filter, capability === item && styles.filterActive]}>
                <Text style={[styles.filterText, capability === item && styles.filterTextActive]}>{item === 'ALL' ? '✦ Recommended for Your PC' : item}</Text>
              </Pressable>
            ))}
            <Pressable onPress={() => void refresh()} style={styles.scanButton}><Text style={styles.scanText}>↻  REFRESH CATALOG</Text></Pressable>
          </View>
        </View>

        <View style={styles.grid}>
      {visibleModels.map((model) => {
        const state = model.installation_status ?? 'unknown';
        const itemProgress = progress[model.model_id];
        const isBusy = busyModel === model.model_id;
        const canInstall = model.installable === true;
        const canActivate = state === 'installed' && ACTIVE_CAPABILITIES.has(model.capability) && !model.is_active;
        const canUninstall = state === 'installed' && !model.is_active && !model.is_pinned;
        return (
          <View key={model.model_id} style={[styles.modelCard, width >= 1120 && styles.modelCardWide]}>
            <View style={styles.modelTitleRow}>
              <Text numberOfLines={2} style={styles.modelName}>{model.name || model.model_id}</Text>
              <Text style={styles.capabilityBadge}>{model.capability}</Text>
            </View>
            <View style={styles.modelMetaRow}>
              <Text numberOfLines={1} style={styles.repoBadge}>◉ {model.upstream_id || model.model_id}</Text>
              <Text style={styles.recommendedBadge}>{model.is_active ? '● Active' : '✦ Recommended'}</Text>
            </View>
            <Text style={styles.modelDetails}>◈ {model.provider || 'Community'}   ⚖ {model.required_runtime || 'local runtime'}</Text>
            {itemProgress && ['downloading', 'installing'].includes(itemProgress.phase) ? (
              <Text style={styles.progress}>
                Progress: {Math.max(0, Math.min(100, itemProgress.percent ?? 0)).toFixed(1)}% · {itemProgress.phase}
              </Text>
            ) : null}
            {itemProgress?.error ? <Text style={{ color: colors.danger }}>{itemProgress.error}</Text> : null}
            {!canInstall && state !== 'installed' && model.installation_reason ? (
              <Text numberOfLines={2} style={styles.reason}>{model.installation_reason}</Text>
            ) : null}
            <View style={styles.cardFooter}>
              <Text style={[styles.state, state === 'installed' && styles.installedState]}>{state === 'installed' ? '● INSTALLED' : '○ READY TO DOWNLOAD'}</Text>
              <View style={styles.actions}>
              {canInstall ? <ActionButton label={isBusy ? 'Starting…' : 'Install'} disabled={isBusy} onPress={() => void install(model)} /> : null}
              {canActivate ? <ActionButton label={isBusy ? 'Activating…' : 'Activate'} disabled={isBusy} onPress={() => void activate(model)} /> : null}
              {canUninstall ? <ActionButton label={isBusy ? 'Removing…' : 'Uninstall'} destructive disabled={isBusy} onPress={() => void uninstall(model)} /> : null}
              </View>
            </View>
          </View>
        );
      })}
        </View>
      {!visibleModels.length && !error ? <Text style={styles.empty}>No models match this view.</Text> : null}
      {message ? <Text style={{ color: colors.success }}>{message}</Text> : null}
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  panel: { backgroundColor: '#0d1420', borderWidth: 1, borderColor: '#233146', borderRadius: 15, overflow: 'hidden' },
  tabs: { minHeight: 48, flexDirection: 'row', alignItems: 'flex-end', borderBottomWidth: 1, borderBottomColor: '#233146', paddingHorizontal: 18, paddingTop: 10, gap: 8 },
  tab: { paddingHorizontal: 18, paddingVertical: 12, borderWidth: 1, borderColor: 'transparent', borderBottomWidth: 0, borderTopLeftRadius: 12, borderTopRightRadius: 12 },
  tabActive: { backgroundColor: '#121b29', borderColor: '#e5e9f0' },
  tabText: { color: '#68778b', fontSize: 14, fontWeight: '700' },
  tabTextActive: { color: '#f5f7fa' },
  panelHeading: { padding: 20, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 14, borderBottomWidth: 1, borderBottomColor: '#1e2a3d' },
  headingCopy: { flexGrow: 1, gap: 4 },
  headingLine: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 9 },
  panelTitle: { color: '#f6f7fb', fontSize: 18, fontWeight: '800' },
  panelSubtitle: { color: '#748297', fontSize: 14 },
  repositoryBadge: { color: '#4e9cff', backgroundColor: '#142846', borderWidth: 1, borderColor: '#224c80', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4, fontSize: 12, fontWeight: '800' },
  hardwareBadge: { color: '#72b4ff', backgroundColor: '#12213a', borderWidth: 1, borderColor: '#254775', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 16, fontSize: 12, fontWeight: '700' },
  discovery: { margin: 20, backgroundColor: '#09101b', borderWidth: 1, borderColor: '#22324a', borderRadius: 14, padding: 16, gap: 16 },
  search: { color: '#e7edf7', minHeight: 46, fontSize: 15, borderBottomWidth: 1, borderBottomColor: '#17243a', paddingHorizontal: 2 },
  filters: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, alignItems: 'center' },
  filter: { backgroundColor: '#172133', borderWidth: 1, borderColor: '#27354b', borderRadius: 18, paddingHorizontal: 15, paddingVertical: 7 },
  filterActive: { backgroundColor: '#142747', borderColor: '#397ed9' },
  filterText: { color: '#77869b', fontSize: 13, fontWeight: '700' },
  filterTextActive: { color: '#8fc4ff' },
  scanButton: { backgroundColor: '#1769e0', borderRadius: 5, paddingHorizontal: 16, paddingVertical: 9 },
  scanText: { color: '#fff', fontWeight: '800', fontSize: 13 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 14, paddingHorizontal: 20, paddingBottom: 20 },
  modelCard: { width: '100%', backgroundColor: '#101824', borderWidth: 1, borderColor: '#2a394f', borderRadius: 14, padding: 18, gap: 12 },
  modelCardWide: { width: '48.9%', flexGrow: 1 },
  modelTitleRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 },
  modelName: { flex: 1, color: '#f6f8fb', fontSize: 16, fontWeight: '800' },
  capabilityBadge: { color: '#63a8ff', backgroundColor: '#122541', borderWidth: 1, borderColor: '#224a78', borderRadius: 4, paddingHorizontal: 9, paddingVertical: 3, fontSize: 12, fontWeight: '800' },
  modelMetaRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  repoBadge: { flexShrink: 1, color: '#73aff7', backgroundColor: '#14233a', borderRadius: 4, paddingHorizontal: 9, paddingVertical: 4, fontSize: 12 },
  recommendedBadge: { color: '#91bdff', backgroundColor: '#172844', borderRadius: 10, paddingHorizontal: 9, paddingVertical: 4, fontSize: 12 },
  modelDetails: { color: '#748298', fontSize: 13 },
  progress: { color: '#8fa0b7', fontSize: 13 },
  reason: { color: '#8290a3', fontSize: 13, lineHeight: 18 },
  cardFooter: { borderTopWidth: 1, borderTopColor: '#202c3e', paddingTop: 12, marginTop: 4, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  state: { color: '#7c899b', fontSize: 12, fontWeight: '800' },
  installedState: { color: '#2acb8a' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  empty: { color: '#8290a3', paddingHorizontal: 20, paddingBottom: 20 },
});
