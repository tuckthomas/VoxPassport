import { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View } from 'react-native';
import type { ModelEntry, ModelInstallProgress, RemoteModelEndpoint } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { RaisedButton } from '@/components/RaisedButton';
import { DropdownMenu } from '@/components/DropdownMenu';
import { FilterTag } from '@/components/FilterTag';
import { IconButton } from '@/components/IconButton';
import { TrashIcon } from '@/components/icons/TrashIcon';
import { StatusLight } from '@/components/StatusLight';
import { StudioShell } from '@/components/StudioShell';
import { WidgetCard } from '@/components/WidgetCard';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';

type ModelTab = 'active' | 'hub' | 'configuration';
const CAPABILITIES = ['TTS', 'ASR', 'TRANSLATION', 'VAD'] as const;
const SECTION_TITLES: Record<(typeof CAPABILITIES)[number], string> = {
  TTS: '1.  TEXT-TO-SPEECH (TTS) VOICE SYNTHESIS ENGINES',
  ASR: '2.  AUTOMATIC SPEECH RECOGNITION (ASR) PIPELINES',
  TRANSLATION: '3.  NEURAL MACHINE TRANSLATION (NMT) ENGINES',
  VAD: '4.  VOICE ACTIVITY DETECTION (VAD) ENGINE',
};

function isRecommended(model: ModelEntry) {
  return model.recommendation_state === 'RECOMMENDED_FOR_LOCAL_BENCHMARK'
    || model.recommendation_state === 'RECOMMENDED_UPGRADE';
}

export default function ModelsScreen() {
  const api = useVoxPassportApi();
  const target = useRuntimeTarget();
  const { width } = useWindowDimensions();
  const [tab, setTab] = useState<ModelTab>('active');
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [progress, setProgress] = useState<Record<string, ModelInstallProgress>>({});
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('ALL');
  const [recommended, setRecommended] = useState(true);
  const [busyModel, setBusyModel] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [modelStore, setModelStore] = useState('');
  const [remoteEndpoints, setRemoteEndpoints] = useState<RemoteModelEndpoint[]>([]);
  const [profileName, setProfileName] = useState('');
  const [profileUrl, setProfileUrl] = useState('');
  const [tokenEnv, setTokenEnv] = useState('');
  const [profileCapabilities, setProfileCapabilities] = useState(['ASR']);
  const [loadedTtsModelId, setLoadedTtsModelId] = useState<string | null>(null);

  const downloading = useMemo(() => models.filter((model) => ['downloading', 'installing'].includes(model.installation_status || '')).map((model) => model.model_id), [models]);
  const activeModels = useMemo(() => models.filter((model) => model.is_active || model.installation_status === 'installed'), [models]);
  const hubModels = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return models.filter((model) => {
      if (model.installation_status === 'installed' || model.is_active) return false;
      if (category !== 'ALL' && model.capability !== category) return false;
      if (recommended && !isRecommended(model)) return false;
      return !needle || [model.name, model.model_id, model.provider, model.upstream_id].some((value) => value?.toLowerCase().includes(needle));
    });
  }, [models, query, category, recommended]);

  async function refresh() {
    try { setModels(await api.models()); setError(''); }
    catch (next) { setError(next instanceof Error ? next.message : String(next)); }
  }

  async function refreshResidency() {
    try {
      const snapshot = await api.resources();
      const runtime = snapshot.tts_runtime as { active_model_id?: unknown; profiles?: Array<{ loaded_model_id?: unknown }> } | undefined;
      const profileModel = runtime?.profiles?.find((profile) => typeof profile.loaded_model_id === 'string')?.loaded_model_id;
      setLoadedTtsModelId(typeof runtime?.active_model_id === 'string' ? runtime.active_model_id : typeof profileModel === 'string' ? profileModel : null);
    } catch {
      setLoadedTtsModelId(null);
    }
  }

  async function loadConfiguration() {
    try {
      const [storage, endpoints] = await Promise.all([api.modelStorage(), api.remoteModelEndpoints()]);
      setModelStore(storage.model_store_dir || '');
      setRemoteEndpoints(endpoints);
    } catch (next) { setError(next instanceof Error ? next.message : String(next)); }
  }

  useEffect(() => {
    if (!target.ready) return;
    void refresh();
    void refreshResidency();
    const timer = setInterval(() => void refreshResidency(), 2000);
    return () => clearInterval(timer);
  }, [api, target.ready]);
  useEffect(() => { if (tab === 'configuration') void loadConfiguration(); }, [tab]);
  useEffect(() => {
    if (!downloading.length) return;
    const timer = setInterval(() => void Promise.all(downloading.map(async (id) => [id, await api.modelInstallProgress(id)] as const)).then((entries) => setProgress((current) => ({ ...current, ...Object.fromEntries(entries) }))), 1200);
    return () => clearInterval(timer);
  }, [api, downloading.join('|')]);

  async function activate(model: ModelEntry) {
    setBusyModel(model.model_id);
    try { await api.activateModel(model.capability, model.model_id); await refresh(); }
    catch (next) { setError(next instanceof Error ? next.message : String(next)); }
    finally { setBusyModel(''); }
  }

  async function install(model: ModelEntry) {
    setBusyModel(model.model_id);
    try { await api.installModel(model.model_id, model.upstream_id, model.revision); setMessage(`Download started for ${model.name || model.model_id}.`); await refresh(); }
    catch (next) { setError(next instanceof Error ? next.message : String(next)); }
    finally { setBusyModel(''); }
  }

  async function saveStorage() {
    try { const result = await api.saveModelStorage(modelStore); setModelStore(result.model_store_dir); setMessage('Default model storage location saved.'); }
    catch (next) { setError(next instanceof Error ? next.message : String(next)); }
  }

  async function browseStorage() {
    try {
      const result = await api.browseModelStorage(modelStore);
      if (!result.success) throw new Error(result.error || 'The folder picker could not be opened.');
      if (!result.cancelled && result.model_store_dir) setModelStore(result.model_store_dir);
    } catch (next) { setError(next instanceof Error ? next.message : String(next)); }
  }

  async function createProfile() {
    try {
      const result = await api.createRemoteModelEndpoint({ name: profileName, base_url: profileUrl, auth_token_env: tokenEnv, capabilities: profileCapabilities });
      if (!result.success) throw new Error(result.error || 'Could not create cloud profile.');
      setProfileName(''); setProfileUrl(''); setTokenEnv(''); await loadConfiguration(); setMessage('Cloud configuration profile created.');
    } catch (next) { setError(next instanceof Error ? next.message : String(next)); }
  }

  const heading = tab === 'active'
    ? ['Active Inference Pipelines', 'FULL DUPLEX ENGINE', 'Real-time hot-swappable TTS, ASR, NMT, and VAD neural slots']
    : tab === 'hub'
      ? ['Model Hub', 'LOCAL + CLOUD DEPLOYMENT', 'Discover models for local download or provider-neutral cloud deployment']
      : ['Configuration', 'RUNTIME SETTINGS', 'Manage reusable cloud worker profiles and default model storage'];

  return (
    <StudioShell>
      <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
        <View style={styles.panel}>
          <View style={styles.tabs}>
            <TabButton label="▣  Active Engines" selected={tab === 'active'} onPress={() => setTab('active')} />
            <TabButton label="⇩  Model Hub" selected={tab === 'hub'} onPress={() => setTab('hub')} />
            <TabButton label="◎  Configuration" selected={tab === 'configuration'} onPress={() => setTab('configuration')} />
          </View>
          <View style={styles.panelHeading}>
            <View style={styles.headingCopy}>
              <View style={styles.headingLine}><Text style={styles.panelTitle}>{heading[0]}</Text><Text style={styles.headingBadge}>{heading[1]}</Text></View>
              <Text style={styles.panelSubtitle}>{heading[2]}</Text>
            </View>
            <Text style={styles.hardwareBadge}>▣ RTX 2070 (8 GB VRAM) · 16-Core CPU · 32 GB RAM</Text>
          </View>

          {tab === 'active' ? <View style={styles.sections}>{CAPABILITIES.map((capability) => (
            <View key={capability} style={styles.section}>
              <Text style={styles.sectionTitle}>{SECTION_TITLES[capability]}</Text>
              <View style={styles.engineGrid}>{activeModels.filter((model) => model.capability === capability).map((model) => <ActiveEngineCard key={model.model_id} model={model} busy={busyModel === model.model_id} wide={width >= 1040} resident={model.capability === 'TTS' && loadedTtsModelId === model.model_id} onLocal={() => void activate(model)} onCloud={() => setTab('configuration')} onMessage={setMessage} />)}</View>
            </View>
          ))}</View> : null}

          {tab === 'hub' ? <View style={styles.hubBody}>
            <View style={styles.discovery}>
              <TextInput value={query} onChangeText={setQuery} placeholder="⌕  Search models by name, publisher, or repository ID..." placeholderTextColor="#69778c" style={styles.search} />
              <View style={styles.filters}>
                <FilterTag label="✨ Recommended for Your PC" selected={recommended} onPress={() => setRecommended((value) => !value)} />
                <View style={styles.filterDivider} />
                {['ALL', 'TTS', 'ASR', 'TRANSLATION', 'VAD'].map((item) => <FilterTag key={item} label={item === 'ALL' ? 'All Models' : item === 'TRANSLATION' ? 'Translation' : item} selected={category === item} onPress={() => setCategory(item)} />)}
                <View style={styles.filterDivider} />
                <FilterTag label="Any Cloud" selected onPress={() => setMessage('Showing provider-neutral deployment options.')} />
                <FilterTag label="AWS" selected={false} onPress={() => setMessage('AWS cloud profiles can be created in Configuration.')} />
                <FilterTag label="Google Colab" selected={false} onPress={() => setMessage('Google Colab profiles can be created in Configuration.')} />
                <FilterTag label="Private VPS" selected={false} onPress={() => setMessage('Private VPS profiles can be created in Configuration.')} />
                <RaisedButton compact label="↻  SCAN HUGGING FACE" onPress={() => void refresh()} />
              </View>
            </View>
            <View style={styles.hubGrid}>{hubModels.map((model) => <HubModelCard key={model.model_id} model={model} progress={progress[model.model_id]} busy={busyModel === model.model_id} wide={width >= 1180} onCloud={() => setTab('configuration')} onDownload={() => void install(model)} />)}</View>
          </View> : null}

          {tab === 'configuration' ? <View style={styles.configurationBody}>
            <View style={styles.configurationGrid}>
              <WidgetCard style={styles.configurationCard}>
                <Text style={styles.configTitle}>⇩  DEFAULT MODEL STORAGE</Text>
                <Text style={styles.configCopy}>Choose where newly downloaded local models and staging files are stored.</Text>
                <View style={styles.inlineForm}><View style={styles.folderField}><TextInput value={modelStore} editable={false} selectTextOnFocus placeholder="Choose a model storage folder" placeholderTextColor="#66758a" style={[styles.input, styles.folderInput]} /><View style={styles.folderButton}><IconButton label="Choose model storage folder" onPress={() => void browseStorage()}><Text style={styles.folderIcon}>📁</Text></IconButton></View></View><RaisedButton compact label="SAVE" onPress={() => void saveStorage()} /></View>
              </WidgetCard>
              <WidgetCard style={styles.configurationCard}>
                <Text style={styles.configTitle}>▱  CREATE CLOUD PROFILE</Text>
                <TextInput value={profileName} onChangeText={setProfileName} placeholder="Profile name (e.g. AWS A10G)" placeholderTextColor="#66758a" style={styles.input} />
                <TextInput value={profileUrl} onChangeText={setProfileUrl} placeholder="https://worker.example.com" placeholderTextColor="#66758a" style={styles.input} />
                <TextInput value={tokenEnv} onChangeText={setTokenEnv} placeholder="Optional token environment variable" placeholderTextColor="#66758a" style={styles.input} />
                <View style={styles.checks}>{['ASR', 'Translation', 'TTS'].map((label) => { const value = label === 'Translation' ? 'TRANSLATION' : label; const checked = profileCapabilities.includes(value); return <Pressable key={value} accessibilityRole="checkbox" accessibilityState={{ checked }} onPress={() => setProfileCapabilities((current) => checked ? current.filter((item) => item !== value) : [...current, value])} style={styles.check}><Text style={[styles.checkBox, checked && styles.checkBoxOn]}>{checked ? '✓' : ''}</Text><Text style={styles.checkLabel}>{label}</Text></Pressable>; })}</View>
                <View style={styles.createButton}><RaisedButton compact label="CREATE PROFILE" disabled={!profileName || !profileUrl || !profileCapabilities.length} onPress={() => void createProfile()} /></View>
              </WidgetCard>
            </View>
            <Text style={styles.configTitle}>⌁  CLOUD CONFIGURATION PROFILES</Text>
            <View style={styles.hubGrid}>{remoteEndpoints.map((endpoint) => <WidgetCard key={endpoint.endpoint_id} style={styles.endpointCard}><Text style={styles.modelName}>{endpoint.name}</Text><Text style={styles.repo}>{endpoint.base_url}</Text><Text style={styles.modelMeta}>{endpoint.capabilities.join(' · ')}</Text></WidgetCard>)}{!remoteEndpoints.length ? <Text style={styles.empty}>No cloud profiles yet.</Text> : null}</View>
          </View> : null}

          {message ? <Text style={styles.message}>{message}</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>
      </ScrollView>
    </StudioShell>
  );
}

function TabButton({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return <Pressable accessibilityRole="tab" accessibilityState={{ selected }} onPress={onPress} style={({ pressed }) => [styles.tabButton, selected && styles.tabButtonSelected, pressed && styles.tabButtonPressed]}><Text style={[styles.tabLabel, selected && styles.tabLabelSelected]}>{label}</Text></Pressable>;
}

function ActiveEngineCard({ model, busy, wide, resident, onLocal, onCloud, onMessage }: { model: ModelEntry; busy: boolean; wide: boolean; resident: boolean; onLocal: () => void; onCloud: () => void; onMessage: (message: string) => void }) {
  const selected = Boolean(model.is_active);
  const statusTone = model.capability === 'TTS' ? resident ? 'green' : selected ? 'white' : 'red' : selected ? 'green' : 'red';
  return <WidgetCard active={Boolean(model.is_active)} style={[styles.engineCard, wide && styles.engineCardWide]}>
    <View style={styles.modelTitleRow}><StatusLight tone={statusTone} size={9} /><Text numberOfLines={1} style={styles.modelName}>{shortModelName(model)}</Text><View style={styles.engineIcons}><Text style={styles.engineIcon}>☁</Text><Text style={styles.engineIcon}>⚖</Text></View><DropdownMenu label={`Options for ${model.name || model.model_id}`} items={[{ key: 'cloud', label: 'Cloud Configuration', icon: '☁', disabled: model.capability === 'VAD', onPress: onCloud }, { key: 'delete-local', label: 'Delete Local Model', icon: <TrashIcon size={12} />, disabled: Boolean(model.is_active || model.is_pinned), danger: true, onPress: () => onMessage('Local model deletion requires confirmation from the model options workflow.') }, { key: 'remove-pipeline', label: 'Delete from Pipeline', icon: '⊘', disabled: Boolean(model.is_active), danger: true, onPress: () => onMessage('Switch the active engine before removing this model from the pipeline.') }]} /></View>
    {model.capability === 'TTS' && selected ? <Text style={[styles.residencyTag, resident ? styles.residentTag : styles.onDemandTag]}>{resident ? 'LOADED IN VRAM' : 'SELECTED · ON DEMAND · NOT LOADED'}</Text> : null}
    <View style={styles.modelInfo}><Text numberOfLines={1} style={styles.modelDescriptor}>{capabilityIcon(model.capability)} {modelDescriptor(model)}</Text><Text style={styles.modelMeta}>{engineMeta(model)}</Text></View>
    <View style={styles.deployRow}><View style={styles.deployButton}><RaisedButton compact label="▣  LOCAL" latched={selected} disabled={busy} onPress={onLocal} /></View><View style={styles.deployButton}><RaisedButton compact label="☁  CLOUD" disabled={model.capability === 'VAD'} backgroundColor="#0284c7" onPress={onCloud} /></View></View>
  </WidgetCard>;
}

function HubModelCard({ model, progress, busy, wide, onCloud, onDownload }: { model: ModelEntry; progress?: ModelInstallProgress; busy: boolean; wide: boolean; onCloud: () => void; onDownload: () => void }) {
  const installed = model.installation_status === 'installed';
  return <WidgetCard style={[styles.hubCard, wide && styles.hubCardWide]}>
    <View style={styles.modelTitleRow}><Text numberOfLines={2} style={styles.modelName}>{model.name || model.model_id}</Text><Text style={styles.capability}>{model.capability === 'TRANSLATION' ? 'Translation' : model.capability}</Text></View>
    <View style={styles.modelInfo}><Text numberOfLines={1} style={styles.repo}>◉ {model.upstream_id || model.model_id}</Text>{isRecommended(model) ? <Text style={styles.recommended}>✨ Recommended</Text> : null}</View>
    <Text style={styles.modelMeta}>📦 {sizeLabel(model)}   🏢 {(model.provider || 'Community').toUpperCase()}   ⚖</Text>
    {progress && ['downloading', 'installing'].includes(progress.phase) ? <Text style={styles.progress}>{progress.percent.toFixed(0)}% · {progress.phase}</Text> : null}
    <View style={styles.hubActions}><RaisedButton compact label="CLOUD" backgroundColor="#0284c7" onPress={onCloud} /><RaisedButton compact label={installed ? 'INSTALLED' : busy ? 'STARTING…' : '⇩  DOWNLOAD'} disabled={installed || busy || !model.installable} onPress={onDownload} /></View>
  </WidgetCard>;
}

function sizeLabel(model: ModelEntry) {
  const value = model.installed_size_gb ?? model.estimated_download_size_gb ?? model.runtime_requirements?.estimated_size_gb;
  return typeof value === 'number' && value > 0 ? `${formatSize(value)} GB` : 'Size varies';
}

function formatSize(value: number) {
  return value < 0.1 ? value.toFixed(2) : value < 1 ? value.toFixed(1) : value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function shortModelName(model: ModelEntry) {
  const names: Record<string, string> = {
    'omnivoice-stock': 'OmniVoice Stock',
    'higgs-tts-3-q4_k_m': 'Higgs TTS 3 Q4 Native',
    'nvidia-parakeet-tdt-0.6b-v3': 'Parakeet TDT 0.6B',
    'xiaomi-milmmt-46-1b-v1.0': 'MiLMMT-46 1B',
  };
  return names[model.model_id] || model.name || model.model_id;
}

function capabilityIcon(capability: string) {
  return capability === 'TRANSLATION' ? '文' : capability === 'VAD' ? '⌁' : '♩';
}

function modelDescriptor(model: ModelEntry) {
  const descriptions: Record<string, string> = {
    'omnivoice-stock': 'Zero-Shot Neural Voice Cloning',
    'higgs-tts-3': 'Multilingual Neural Voice Cloning',
    'higgs-tts-3-q4_k_m': 'Compiled audiocpp CUDA Voice Cloning',
    'nvidia-parakeet-tdt-0.6b-v3': 'FastConformer RNNT',
    'xiaomi-milmmt-46-1b-v1.0': 'Multilingual Neural NMT',
    'silero-vad-v4': 'Neural Voice Activity Detection',
  };
  return descriptions[model.model_id] || model.required_runtime || model.capability;
}

function engineMeta(model: ModelEntry) {
  const prefix = model.capability === 'VAD' ? '32ms' : model.capability === 'TTS' ? '24kHz' : model.capability === 'ASR' ? '16kHz' : '46-Lang';
  return `${prefix} · ${sizeLabel(model)}`;
}

const styles = StyleSheet.create({
  page: { width: '100%', maxWidth: 1120, alignSelf: 'center', padding: 20 },
  panel: { backgroundColor: '#101622', borderWidth: 1, borderColor: '#1c2638', borderRadius: 14, overflow: 'hidden' },
  tabs: { minHeight: 48, flexDirection: 'row', alignItems: 'flex-end', paddingHorizontal: 18, paddingTop: 12, gap: 8, backgroundColor: '#0c121e', borderBottomWidth: 1, borderBottomColor: '#1c2638' },
  tabButton: { minWidth: 145, minHeight: 36, paddingHorizontal: 20, paddingVertical: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,.03)', borderWidth: 1, borderColor: '#1c2638', borderBottomWidth: 0, borderTopLeftRadius: 10, borderTopRightRadius: 10, opacity: 0.75, transform: [{ translateY: 1 }] },
  tabButtonSelected: { backgroundColor: '#101622', borderColor: '#1c2638', opacity: 1 }, tabButtonPressed: { backgroundColor: 'rgba(255,255,255,.06)', opacity: 1 },
  tabLabel: { color: '#64748b', fontSize: 13, fontWeight: '700' }, tabLabelSelected: { color: '#f8fafc' },
  panelHeading: { paddingHorizontal: 20, paddingVertical: 14, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12, borderBottomWidth: 1, borderBottomColor: '#1c2638' },
  headingCopy: { flex: 1, minWidth: 300, gap: 3 }, headingLine: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  panelTitle: { color: '#f8fafc', fontSize: 14, fontWeight: '800' }, panelSubtitle: { color: '#64748b', fontSize: 13 },
  headingBadge: { color: '#60a5fa', backgroundColor: '#122541', borderWidth: 1, borderColor: '#224a78', borderRadius: 3, paddingHorizontal: 8, paddingVertical: 2, fontSize: 13, fontWeight: '800' },
  hardwareBadge: { color: '#93c5fd', backgroundColor: '#14233a', borderWidth: 1, borderColor: '#294c79', borderRadius: 13, paddingHorizontal: 10, paddingVertical: 5, fontSize: 13, fontWeight: '700' },
  sections: { padding: 20, gap: 24 }, section: { gap: 12 }, sectionTitle: { color: '#93c5fd', fontSize: 13, fontWeight: '800', letterSpacing: 0.6, textTransform: 'uppercase' },
  engineGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 14, alignItems: 'stretch' }, engineCard: { width: '100%', minHeight: 116 }, engineCardWide: { width: '31.8%' },
  modelTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  modelName: { flex: 1, color: '#f8fafc', fontSize: 13, fontWeight: '700' }, engineIcons: { flexDirection: 'row', alignItems: 'center', gap: 7 }, engineIcon: { color: '#94a3b8', fontSize: 13 },
  residencyTag: { alignSelf: 'flex-start', fontSize: 13, fontWeight: '700', paddingHorizontal: 7, paddingVertical: 2, borderRadius: 999, textTransform: 'uppercase', letterSpacing: 0.3, borderWidth: 1 }, residentTag: { color: '#6ee7b7', backgroundColor: 'rgba(16,185,129,.1)', borderColor: 'rgba(16,185,129,.3)' }, onDemandTag: { color: '#60a5fa', backgroundColor: 'rgba(59,130,246,.12)', borderColor: 'rgba(59,130,246,.25)' },
  modelInfo: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 6, marginTop: 2, marginBottom: 4 }, modelDescriptor: { flexShrink: 1, color: '#94a3b8', backgroundColor: '#172030', borderWidth: 1, borderColor: '#1c2638', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3, fontSize: 13, fontWeight: '600' }, modelMeta: { color: '#64748b', fontFamily: 'monospace', fontSize: 13 },
  deployRow: { flexDirection: 'row', gap: 7, marginTop: 'auto' }, deployButton: { flex: 1 },
  hubBody: { padding: 20, gap: 16 }, discovery: { backgroundColor: '#0b0f19', borderWidth: 1, borderColor: '#25334a', borderRadius: 12, padding: 16, gap: 12 }, search: { minHeight: 40, color: '#e2e8f0', borderBottomWidth: 1, borderBottomColor: '#1c2638', fontSize: 13 }, filters: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, filterDivider: { width: 1, height: 20, backgroundColor: '#25334a' },
  hubGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 14 }, hubCard: { width: '100%', paddingHorizontal: 18, paddingVertical: 16, gap: 14, backgroundColor: '#101622', borderColor: '#25334a', borderRadius: 14, boxShadow: '0 4px 16px rgba(0,0,0,.25)' }, hubCardWide: { width: '48.9%' }, capability: { color: '#60a5fa', backgroundColor: '#122541', borderWidth: 1, borderColor: '#224a78', borderRadius: 3, paddingHorizontal: 8, paddingVertical: 3, fontSize: 13, fontWeight: '800' }, repo: { flexShrink: 1, color: '#93c5fd', backgroundColor: '#14233a', borderWidth: 1, borderColor: '#294c79', borderRadius: 4, paddingHorizontal: 8, paddingVertical: 3, fontSize: 13, fontFamily: 'monospace' }, recommended: { color: '#93c5fd', backgroundColor: 'rgba(59,130,246,.15)', borderWidth: 1, borderColor: 'rgba(59,130,246,.35)', borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2, fontSize: 13, fontWeight: '700' }, hubActions: { flexDirection: 'row', gap: 7, borderTopWidth: 1, borderTopColor: '#1c2638', paddingTop: 10 }, progress: { color: '#93c5fd', fontSize: 13 },
  configurationBody: { padding: 20, gap: 18 }, configurationGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 }, configurationCard: { flex: 1, minWidth: 320, padding: 18, gap: 10 }, configTitle: { color: '#93c5fd', fontSize: 13, fontWeight: '800', letterSpacing: 0.5 }, configCopy: { color: '#94a3b8', fontSize: 13, lineHeight: 18 }, input: { flex: 1, minHeight: 40, color: '#e2e8f0', backgroundColor: '#0b0f19', borderWidth: 1, borderColor: '#25334a', borderRadius: 6, paddingHorizontal: 12, fontSize: 13 }, inlineForm: { flexDirection: 'row', alignItems: 'center', gap: 8 }, folderField: { flex: 1, position: 'relative' }, folderInput: { paddingRight: 44 }, folderButton: { position: 'absolute', right: 12, top: 11 }, folderIcon: { color: '#60a5fa', fontSize: 15, lineHeight: 18 }, checks: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 }, check: { flexDirection: 'row', alignItems: 'center', gap: 5 }, checkBox: { width: 14, height: 14, borderWidth: 1, borderColor: '#64748b', color: '#ffffff', fontSize: 13, lineHeight: 16, textAlign: 'center' }, checkBoxOn: { backgroundColor: '#2563eb', borderColor: '#60a5fa' }, checkLabel: { color: '#94a3b8', fontSize: 13 }, createButton: { alignItems: 'flex-start' }, endpointCard: { width: '48%', padding: 14 }, empty: { color: '#64748b', fontSize: 13 }, message: { marginHorizontal: 20, marginBottom: 14, color: '#34d399', fontSize: 13 }, error: { marginHorizontal: 20, marginBottom: 14, color: '#f87171', fontSize: 13 },
});
