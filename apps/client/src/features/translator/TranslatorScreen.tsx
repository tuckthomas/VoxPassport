import { useEffect, useMemo, useState } from 'react';
import {
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import type {
  LanguageConfiguration,
  LiveTranslationMode,
  LiveTranslationSessionStatus,
  TranslationResponse,
  TranslationStrategyDescriptor,
  TranslationStrategyStatus,
} from '@/api/contracts';
import { LiveTranslationClient } from '@/api/liveTranslationClient';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { StudioShell } from '@/components/StudioShell';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';

const MODULAR_STRATEGY_ID = 'modular-pipeline';

export default function TranslatorScreen() {
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const { width } = useWindowDimensions();
  const compact = width < 820;
  const liveApi = useMemo(() => new LiveTranslationClient(target.activeBaseUrl), [target.activeBaseUrl]);
  const [activeTab, setActiveTab] = useState<'live' | 'debug'>('live');
  const [languages, setLanguages] = useState<LanguageConfiguration | null>(null);
  const [source, setSource] = useState('en');
  const [destination, setDestination] = useState('ro');
  const [input, setInput] = useState('');
  const [result, setResult] = useState<TranslationResponse | null>(null);
  const [strategies, setStrategies] = useState<TranslationStrategyDescriptor[]>([]);
  const [strategy, setStrategy] = useState<TranslationStrategyStatus | null>(null);
  const [live, setLive] = useState<LiveTranslationSessionStatus | null>(null);
  const [liveMode] = useState<LiveTranslationMode>('full_duplex');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  async function refreshConfiguration() {
    const [configuration, discovered, active, currentLive] = await Promise.all([
      api.languages(),
      api.translationStrategies(),
      api.translationStrategyStatus(),
      liveApi.status(),
    ]);
    setLanguages(configuration);
    setSource(configuration.user_language || 'en');
    setDestination(configuration.remote_language || 'ro');
    setStrategies(discovered.strategies);
    setStrategy(active);
    setLive(currentLive);
  }

  useEffect(() => {
    if (!target.ready) return;
    refreshConfiguration().catch((next) => setError(next instanceof Error ? next.message : String(next)));
  }, [target.ready, target.activeBaseUrl]);

  useEffect(() => {
    if (!live?.active) return;
    const handle = setInterval(() => {
      liveApi.status().then(setLive).catch((next) => setError(next instanceof Error ? next.message : String(next)));
    }, 500);
    return () => clearInterval(handle);
  }, [live?.active, liveApi]);

  async function translate() {
    if (!input.trim() || busy || strategy?.kind === 'direct_speech_translation') return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      setResult(await api.translate(input.trim(), source.trim().toLowerCase(), destination.trim().toLowerCase()));
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  async function selectStrategy(strategyId: string) {
    if (busy || live?.active || strategy?.strategy_id === strategyId) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const validation = await api.validateTranslationStrategy(strategyId, source, destination);
      if (!validation.valid || validation.auth_configured === false) {
        throw new Error(validation.reason || 'Translation engine is unavailable.');
      }
      setStrategy(await api.activateTranslationStrategy(strategyId, source, destination));
      setResult(null);
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  async function toggleLive() {
    if (busy) return;
    if (strategy?.kind !== 'direct_speech_translation') {
      setMessage('The local modular capture pipeline is ready in the runtime.');
      return;
    }
    setBusy(true);
    setError('');
    setMessage('');
    try {
      setLive(live?.active
        ? await liveApi.stop()
        : await liveApi.start({ source_language: source, target_language: destination, mode: liveMode }));
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  function swapLanguages() {
    if (live?.active) return;
    setSource(destination);
    setDestination(source);
    if (result) {
      setInput(result.translated_text);
      setResult(null);
    }
  }

  const outbound = live?.leg_captions?.outbound;
  const sourceCaption = outbound?.source ?? live?.source_caption ?? '';
  const targetCaption = outbound?.translation ?? live?.translated_caption ?? '';
  const destinationName = destination.toLowerCase() === 'ro' ? 'ROMANIAN' : destination.toUpperCase();

  return (
    <StudioShell>
    <SafeAreaView style={styles.root}>
      <View style={styles.tabBar}>
        <StudioTab label="Live Mode" icon="◉" active={activeTab === 'live'} onPress={() => setActiveTab('live')} />
        <StudioTab label="Debug Mode" icon="☆" active={activeTab === 'debug'} onPress={() => setActiveTab('debug')} />
        <View style={styles.runtimeStatus}>
          <View style={styles.onlineDot} />
          <Text style={styles.runtimeStatusText}>{target.mode.toUpperCase()} RUNTIME</Text>
        </View>
      </View>

      {activeTab === 'live' ? (
        <ScrollView contentContainerStyle={[styles.workspace, compact && styles.workspaceCompact]}>
          <View style={[styles.column, compact && styles.columnCompact]}>
            <StudioPanel style={styles.fillPanel}>
              <PaneHeader title="Live Source Speech" badge="PARAKEET-TDT-CTC-110M" subtitle="Real-Time Dictation Stream" />
              <View style={styles.paneBody}>
                <View style={styles.micBar}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={live?.active ? 'Stop live recording' : 'Start live recording'}
                    onPress={() => void toggleLive()}
                    style={({ pressed }) => [styles.recordButton, pressed && styles.pressed]}
                  >
                    <Text style={styles.recordButtonText}>● {live?.active ? 'STOP STREAM' : 'LIVE RECORD'}</Text>
                  </Pressable>
                  <Waveform active={Boolean(live?.active)} />
                </View>
                <View style={styles.transcriptBox}>
                  <Text style={[styles.transcriptText, !sourceCaption && styles.placeholderText]}>
                    {sourceCaption || 'Source speech will appear here...'}
                  </Text>
                </View>
              </View>
              <PaneFooter left={live?.active ? 'Mic Active • Streaming' : 'Mic Inactive • Ready'} right={`${wordCount(sourceCaption)} words`} />
            </StudioPanel>
          </View>

          <View style={[styles.divider, compact && styles.dividerCompact]}>
            {!compact ? <View style={styles.dividerLine} /> : null}
            <Text style={styles.dividerLabel}>TARGET</Text>
            <Pressable accessibilityRole="button" onPress={swapLanguages} style={styles.languagePill}>
              <Text style={styles.languagePillText}>{destinationName === 'ROMANIAN' ? '🇷🇴 RO' : destination.toUpperCase()}</Text>
            </Pressable>
            <Pressable accessibilityRole="button" onPress={swapLanguages} style={styles.streamArrow}>
              <Text style={styles.streamArrowText}>{compact ? '↓' : '→'}</Text>
            </Pressable>
            <Text style={[styles.dividerLabel, styles.autoStream]}>AUTO STREAM</Text>
            {!compact ? <View style={styles.dividerLine} /> : null}
          </View>

          <View style={[styles.column, styles.connectedColumn, compact && styles.columnCompact]}>
            <StudioPanel style={styles.halfPanel} connected="bottom">
              <PaneHeader title="Target Language Captions" badge={destinationName} subtitle="MiLMMT-46-1B · Live Stream" />
              <View style={styles.paneBodyTight}>
                <View style={styles.translationBox}>
                  <Text style={[styles.transcriptText, !targetCaption && styles.placeholderText, !targetCaption && styles.italic]}>
                    {targetCaption || 'Awaiting live speech stream...'}
                  </Text>
                </View>
              </View>
            </StudioPanel>
            <StudioPanel style={styles.halfPanel} connected="top">
              <PaneHeader title="Live Cloned Audio Stream" badge="HIGGS Q4 NATIVE" subtitle="Active Voice Profile Output" />
              <View style={[styles.paneBodyTight, styles.audioBody]}>
                <Waveform active={Boolean(live?.translated_audio_chunks)} large />
              </View>
              <PaneFooter left="Zero-Shot Neural Cloner" right={`Latency: ${result ? `${result.latency_ms.toFixed(0)} ms` : '—'}`} />
            </StudioPanel>
          </View>
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={[styles.workspace, compact && styles.workspaceCompact]}>
          <View style={[styles.column, compact && styles.columnCompact]}>
            <StudioPanel style={styles.fillPanel}>
              <PaneHeader title="English Source" badge="PARAKEET-TDT-CTC-110M" subtitle="ASR · Real-Time Transcription" />
              <View style={styles.paneBody}>
                <View style={styles.engineStrip}>
                  <EngineChoice title="Local Modular" active={strategy?.strategy_id === MODULAR_STRATEGY_ID} disabled={busy || Boolean(live?.active)} onPress={() => void selectStrategy(MODULAR_STRATEGY_ID)} />
                  {strategies.map((item) => (
                    <EngineChoice key={item.strategy_id} title={item.display_name} active={strategy?.strategy_id === item.strategy_id} disabled={busy || Boolean(live?.active)} onPress={() => void selectStrategy(item.strategy_id)} />
                  ))}
                </View>
                <TextInput value={input} onChangeText={setInput} multiline placeholder="Type or dictate source text..." placeholderTextColor={palette.textDim} style={styles.textArea} />
              </View>
              <PaneFooter left={`${languages?.supported.length ?? 0} language codes available`} right={`${wordCount(input)} words`} />
            </StudioPanel>
          </View>

          <View style={[styles.divider, compact && styles.dividerCompact]}>
            {!compact ? <View style={styles.dividerLine} /> : null}
            <Text style={styles.dividerLabel}>TARGET</Text>
            <Pressable accessibilityRole="button" onPress={swapLanguages} style={styles.languagePill}>
              <Text style={styles.languagePillText}>{source.toUpperCase()} → {destination.toUpperCase()}</Text>
            </Pressable>
            <Pressable accessibilityRole="button" accessibilityLabel="Translate text" disabled={busy || !input.trim() || strategy?.kind === 'direct_speech_translation'} onPress={() => void translate()} style={({ pressed }) => [styles.translateButton, pressed && styles.pressed]}>
              <Text style={styles.translateButtonText}>{compact ? '↓' : '→'}</Text>
            </Pressable>
            <Text style={[styles.dividerLabel, styles.autoStream]}>{busy ? 'TRANSLATING' : 'TRANSLATE'}</Text>
            {!compact ? <View style={styles.dividerLine} /> : null}
          </View>

          <View style={[styles.column, compact && styles.columnCompact]}>
            <StudioPanel style={styles.fillPanel}>
              <PaneHeader title="Target Language Captions" badge={destinationName} subtitle="NMT · Translation Output" />
              <View style={styles.paneBody}>
                <View style={styles.translationBox}>
                  <Text selectable style={[styles.transcriptText, !result && styles.placeholderText, !result && styles.italic]}>
                    {result?.translated_text ?? 'Translation output will appear here...'}
                  </Text>
                </View>
              </View>
              <PaneFooter left="MiLMMT Neural Translation" right={result ? `${result.latency_ms.toFixed(1)} ms` : 'Ready'} />
            </StudioPanel>
          </View>
        </ScrollView>
      )}

      {message || error ? (
        <View style={[styles.toast, error ? styles.toastError : styles.toastSuccess]}>
          <Text style={styles.toastText}>{error || message}</Text>
        </View>
      ) : null}
    </SafeAreaView>
    </StudioShell>
  );
}

function StudioTab({ label, icon, active, onPress }: { label: string; icon: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="tab" accessibilityState={{ selected: active }} onPress={onPress} style={[styles.tab, active && styles.tabActive]}>
      <Text style={[styles.tabText, active && styles.tabTextActive]}>{icon}  {label}</Text>
    </Pressable>
  );
}

function StudioPanel({ children, style, connected }: { children: React.ReactNode; style?: object; connected?: 'top' | 'bottom' }) {
  return <View style={[styles.panel, connected === 'top' && styles.connectedTop, connected === 'bottom' && styles.connectedBottom, style]}>{children}</View>;
}

function PaneHeader({ title, badge, subtitle }: { title: string; badge: string; subtitle: string }) {
  return (
    <View style={styles.paneHeader}>
      <View style={styles.paneTitleRow}>
        <Text style={styles.paneTitle}>{title}</Text>
        <View style={styles.badge}><Text style={styles.badgeText}>{badge}</Text></View>
      </View>
      <Text style={styles.paneSubtitle}>{subtitle}</Text>
    </View>
  );
}

function PaneFooter({ left, right }: { left: string; right: string }) {
  return (
    <View style={styles.paneFooter}>
      <Text style={styles.footerText}>{left}</Text>
      <View style={styles.metricBadge}><Text style={styles.metricText}>{right}</Text></View>
    </View>
  );
}

function Waveform({ active = false, large = false }: { active?: boolean; large?: boolean }) {
  const bars = [8, 16, 11, 22, 14, 27, 18, 10, 24, 15, 30, 13, 20, 9, 25, 17, 12, 28, 15, 21, 10, 18, 8, 23];
  return (
    <View style={[styles.waveform, large && styles.waveformLarge]}>
      {bars.map((height, index) => <View key={index} style={[styles.waveBar, { height: active ? height : 2 }, active && index % 3 === 0 && styles.waveBarBright]} />)}
    </View>
  );
}

function EngineChoice({ title, active, disabled, onPress }: { title: string; active: boolean; disabled: boolean; onPress: () => void }) {
  return (
    <Pressable disabled={disabled} onPress={onPress} style={[styles.engineChoice, active && styles.engineChoiceActive, disabled && styles.disabled]}>
      <Text numberOfLines={1} style={[styles.engineChoiceText, active && styles.engineChoiceTextActive]}>{active ? '●' : '○'} {title}</Text>
    </Pressable>
  );
}

function wordCount(value: string) {
  return value.trim() ? value.trim().split(/\s+/).length : 0;
}

const palette = {
  background: '#090d16', surface: '#101622', input: '#0b0f19', borderSubtle: '#1c2638', border: '#25334a',
  heading: '#f8fafc', body: '#cbd5e1', muted: '#94a3b8', textDim: '#64748b', accent: '#3b82f6',
  accentDark: '#2563eb', success: '#10b981', danger: '#ef4444',
};

const font = 'Plus Jakarta Sans, system-ui, -apple-system, sans-serif';

const styles = StyleSheet.create({
  root: { flex: 1, minHeight: '100%', backgroundColor: palette.background },
  tabBar: { height: 48, flexDirection: 'row', alignItems: 'flex-end', gap: 8, paddingHorizontal: 20, borderBottomWidth: 1, borderBottomColor: palette.borderSubtle, backgroundColor: palette.background },
  tab: { height: 36, justifyContent: 'center', paddingHorizontal: 20, borderWidth: 1, borderBottomWidth: 0, borderColor: palette.borderSubtle, borderTopLeftRadius: 10, borderTopRightRadius: 10, backgroundColor: 'rgba(255,255,255,0.03)', opacity: 0.72 },
  tabActive: { backgroundColor: palette.surface, opacity: 1 },
  tabText: { fontFamily: font, color: palette.textDim, fontSize: 13, fontWeight: '700' },
  tabTextActive: { color: palette.heading },
  runtimeStatus: { marginLeft: 'auto', height: 36, flexDirection: 'row', alignItems: 'center', gap: 7 },
  runtimeStatusText: { fontFamily: font, color: palette.textDim, fontSize: 11, fontWeight: '700', letterSpacing: 0.8 },
  onlineDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: palette.success },
  workspace: { flexGrow: 1, minHeight: 600, padding: 20, flexDirection: 'row', alignItems: 'stretch' },
  workspaceCompact: { flexDirection: 'column', minHeight: 900 },
  column: { flex: 1, minWidth: 0 },
  columnCompact: { width: '100%', minHeight: 400 },
  connectedColumn: { gap: 0 },
  fillPanel: { flex: 1 },
  halfPanel: { flex: 1, minHeight: 260 },
  panel: { overflow: 'hidden', backgroundColor: palette.surface, borderWidth: 1, borderColor: palette.borderSubtle, borderRadius: 14, boxShadow: '0 4px 20px rgba(0,0,0,0.45)' },
  connectedBottom: { borderBottomLeftRadius: 0, borderBottomRightRadius: 0, borderBottomWidth: 0 },
  connectedTop: { borderTopLeftRadius: 0, borderTopRightRadius: 0 },
  paneHeader: { minHeight: 58, paddingHorizontal: 18, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: palette.borderSubtle, backgroundColor: 'rgba(0,0,0,0.15)', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  paneTitleRow: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  paneTitle: { fontFamily: font, color: palette.heading, fontSize: 14, lineHeight: 18, fontWeight: '800' },
  paneSubtitle: { maxWidth: 180, fontFamily: font, color: palette.textDim, fontSize: 11, lineHeight: 15, textAlign: 'right' },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4, borderWidth: 1, borderColor: 'rgba(59,130,246,0.3)', backgroundColor: 'rgba(59,130,246,0.1)' },
  badgeText: { fontFamily: font, color: '#60a5fa', fontSize: 10, lineHeight: 12, fontWeight: '800', letterSpacing: 0.4 },
  paneBody: { flex: 1, minHeight: 0, padding: 16, gap: 12 },
  paneBodyTight: { flex: 1, minHeight: 0, padding: 14 },
  audioBody: { justifyContent: 'center' },
  micBar: { minHeight: 50, padding: 10, flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: palette.input, borderWidth: 1, borderColor: palette.borderSubtle, borderRadius: 6 },
  recordButton: { minHeight: 34, minWidth: 136, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 15, backgroundColor: palette.danger, borderWidth: 1, borderColor: '#f87171', borderRadius: 4, boxShadow: '0 3px 8px rgba(239,68,68,0.3)' },
  recordButtonText: { fontFamily: font, color: '#ffffff', fontSize: 12, fontWeight: '800', letterSpacing: 0.3 },
  waveform: { flex: 1, minWidth: 80, height: 30, paddingHorizontal: 8, flexDirection: 'row', justifyContent: 'space-around', alignItems: 'center', overflow: 'hidden', backgroundColor: palette.surface, borderWidth: 1, borderColor: palette.borderSubtle, borderRadius: 4 },
  waveformLarge: { width: '100%', flex: 0, height: 46 },
  waveBar: { width: 2, minHeight: 2, borderRadius: 1, backgroundColor: '#334155' },
  waveBarBright: { backgroundColor: '#60a5fa' },
  transcriptBox: { flex: 1, minHeight: 280, padding: 16, backgroundColor: palette.input, borderWidth: 1, borderColor: palette.border, borderRadius: 10 },
  translationBox: { flex: 1, minHeight: 130, padding: 16, backgroundColor: palette.input, borderWidth: 1, borderColor: palette.border, borderRadius: 10 },
  transcriptText: { fontFamily: font, color: palette.heading, fontSize: 15, lineHeight: 24, fontWeight: '500' },
  placeholderText: { color: palette.textDim },
  italic: { fontStyle: 'italic' },
  paneFooter: { minHeight: 46, paddingHorizontal: 18, paddingVertical: 10, borderTopWidth: 1, borderTopColor: palette.borderSubtle, backgroundColor: 'rgba(0,0,0,0.15)', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  footerText: { fontFamily: font, color: palette.textDim, fontSize: 11 },
  metricBadge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4, borderWidth: 1, borderColor: 'rgba(59,130,246,0.3)', backgroundColor: 'rgba(59,130,246,0.08)' },
  metricText: { fontFamily: 'JetBrains Mono, monospace', color: '#60a5fa', fontSize: 11, fontWeight: '600' },
  divider: { width: 96, alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 20 },
  dividerCompact: { width: '100%', minHeight: 96, flexDirection: 'row', paddingVertical: 12 },
  dividerLine: { width: 1, flex: 1, minHeight: 30, backgroundColor: palette.borderSubtle },
  dividerLabel: { fontFamily: font, color: palette.textDim, fontSize: 10, fontWeight: '700', letterSpacing: 0.6 },
  autoStream: { opacity: 0.6 },
  languagePill: { minWidth: 80, paddingHorizontal: 8, paddingVertical: 5, alignItems: 'center', backgroundColor: palette.input, borderWidth: 1, borderColor: palette.border, borderRadius: 10 },
  languagePillText: { fontFamily: font, color: palette.body, fontSize: 11, fontWeight: '700' },
  streamArrow: { width: 42, height: 42, borderRadius: 22, justifyContent: 'center', alignItems: 'center', backgroundColor: 'rgba(16,185,129,0.15)', borderWidth: 1, borderColor: 'rgba(16,185,129,0.35)' },
  streamArrowText: { color: palette.success, fontSize: 24, lineHeight: 28 },
  translateButton: { width: 44, height: 44, borderRadius: 24, justifyContent: 'center', alignItems: 'center', backgroundColor: palette.accentDark, borderWidth: 1, borderColor: palette.accent, boxShadow: '0 4px 16px rgba(59,130,246,0.4)' },
  translateButtonText: { color: '#ffffff', fontSize: 24, lineHeight: 28 },
  engineStrip: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  engineChoice: { maxWidth: 230, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 5, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.input },
  engineChoiceActive: { borderColor: palette.accent, backgroundColor: 'rgba(59,130,246,0.1)' },
  engineChoiceText: { fontFamily: font, color: palette.muted, fontSize: 11, fontWeight: '700' },
  engineChoiceTextActive: { color: '#60a5fa' },
  disabled: { opacity: 0.5 },
  textArea: { flex: 1, minHeight: 300, padding: 16, color: palette.heading, fontFamily: font, fontSize: 15, lineHeight: 24, textAlignVertical: 'top', backgroundColor: palette.input, borderWidth: 1, borderColor: palette.border, borderRadius: 10 },
  toast: { position: 'absolute', left: 20, right: 20, bottom: 16, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 6, borderWidth: 1 },
  toastSuccess: { backgroundColor: 'rgba(16,185,129,0.14)', borderColor: 'rgba(16,185,129,0.4)' },
  toastError: { backgroundColor: 'rgba(239,68,68,0.14)', borderColor: 'rgba(239,68,68,0.4)' },
  toastText: { fontFamily: font, color: palette.heading, fontSize: 13, fontWeight: '600', textAlign: 'center' },
  pressed: { opacity: 0.82 },
});
