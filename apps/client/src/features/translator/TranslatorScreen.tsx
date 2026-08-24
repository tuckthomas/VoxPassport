import { useEffect, useMemo, useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
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
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { colors, theme } from '@/theme';

const MODULAR_STRATEGY_ID = 'modular-pipeline';

export default function TranslatorScreen() {
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const liveApi = useMemo(() => new LiveTranslationClient(target.activeBaseUrl), [target.activeBaseUrl]);
  const [languages, setLanguages] = useState<LanguageConfiguration | null>(null);
  const [source, setSource] = useState('en');
  const [destination, setDestination] = useState('ro');
  const [input, setInput] = useState('');
  const [result, setResult] = useState<TranslationResponse | null>(null);
  const [strategies, setStrategies] = useState<TranslationStrategyDescriptor[]>([]);
  const [strategy, setStrategy] = useState<TranslationStrategyStatus | null>(null);
  const [live, setLive] = useState<LiveTranslationSessionStatus | null>(null);
  const [liveMode, setLiveMode] = useState<LiveTranslationMode>('full_duplex');
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
    if (!live?.active) {
      setSource(configuration.user_language || 'en');
      setDestination(configuration.remote_language || 'ro');
    }
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
      liveApi.status()
        .then(setLive)
        .catch((next) => setError(next instanceof Error ? next.message : String(next)));
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
      if (!validation.valid) throw new Error(validation.reason || 'Translation engine is unavailable.');
      if (validation.auth_configured === false) {
        throw new Error(validation.reason || 'This provider requires a configured API credential.');
      }
      const active = await api.activateTranslationStrategy(strategyId, source, destination);
      setStrategy(active);
      setResult(null);
      setMessage(strategyId === MODULAR_STRATEGY_ID ? 'Local modular pipeline activated.' : 'Direct speech engine activated.');
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  async function startLive() {
    if (busy || strategy?.kind !== 'direct_speech_translation') return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const status = await liveApi.start({
        source_language: source,
        target_language: destination,
        mode: liveMode,
      });
      setLive(status);
      setMessage('Live translation started.');
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  async function stopLive() {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      setLive(await liveApi.stop());
      setMessage('Live translation stopped.');
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

  const directActive = strategy?.kind === 'direct_speech_translation';
  const outbound = live?.leg_captions?.outbound;
  const inbound = live?.leg_captions?.inbound;

  return (
    <Screen
      title="Translator"
      subtitle={`${target.mode}: ${target.activeBaseUrl}`}
    >
      <Card title="Translation engine" subtitle={strategy ? `Active: ${strategy.strategy_id}` : 'Loading engine state…'}>
        <EngineButton
          title="Local Modular"
          detail="VAD → ASR → NMT → TTS · local/private"
          active={strategy?.strategy_id === MODULAR_STRATEGY_ID}
          disabled={Boolean(live?.active || busy)}
          onPress={() => void selectStrategy(MODULAR_STRATEGY_ID)}
        />
        {strategies.map((item) => (
          <EngineButton
            key={item.strategy_id}
            title={item.display_name}
            detail={`${item.execution_mode.replace('_', ' ')} · ${item.provider} · ${item.lifecycle}`}
            active={strategy?.strategy_id === item.strategy_id}
            disabled={Boolean(live?.active || busy)}
            onPress={() => void selectStrategy(item.strategy_id)}
          />
        ))}
      </Card>

      <Card title="Language pair" subtitle={languages ? `${languages.supported.length} runtime language codes reported` : 'Loading runtime languages…'}>
        <View style={{ flexDirection: 'row', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <LanguageInput label="You" value={source} onChange={setSource} disabled={Boolean(live?.active)} />
          <Pressable disabled={Boolean(live?.active)} onPress={swapLanguages} style={buttonStyle}>
            <Text style={{ color: colors.text }}>Swap</Text>
          </Pressable>
          <LanguageInput label="Other party" value={destination} onChange={setDestination} disabled={Boolean(live?.active)} />
        </View>
      </Card>

      {directActive ? (
        <Card
          title="Live speech translation"
          subtitle="PCM stays in the native runtime media plane. This screen polls state/captions only."
        >
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            <ModeButton label="Full duplex" value="full_duplex" selected={liveMode} disabled={Boolean(live?.active)} onSelect={setLiveMode} />
            <ModeButton label="Outbound only" value="outbound" selected={liveMode} disabled={Boolean(live?.active)} onSelect={setLiveMode} />
            <ModeButton label="Inbound only" value="inbound" selected={liveMode} disabled={Boolean(live?.active)} onSelect={setLiveMode} />
          </View>

          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
            {!live?.active ? (
              <Pressable disabled={busy} onPress={() => void startLive()} style={[buttonStyle, { borderColor: colors.success }]}>
                <Text style={{ color: colors.text }}>{busy ? 'Starting…' : 'Start live translation'}</Text>
              </Pressable>
            ) : (
              <Pressable disabled={busy} onPress={() => void stopLive()} style={[buttonStyle, { borderColor: colors.danger }]}>
                <Text style={{ color: colors.text }}>{busy ? 'Stopping…' : 'Stop'}</Text>
              </Pressable>
            )}
          </View>

          <StatusLine label="State" value={live?.state ?? 'stopped'} />
          <StatusLine label="Mode" value={live?.mode ?? liveMode} />
          <StatusLine label="Frames forwarded" value={String(live?.frames_forwarded ?? 0)} />
          <StatusLine label="Translated audio chunks" value={String(live?.translated_audio_chunks ?? 0)} />
          {live?.error ? <Text style={{ color: colors.danger }}>Session error: {live.error}</Text> : null}
        </Card>
      ) : (
        <Card title="Text translation" subtitle="Available while the local modular pipeline is selected.">
          <TextInput
            value={input}
            onChangeText={setInput}
            multiline
            placeholder="Enter text to translate"
            placeholderTextColor={colors.muted}
            style={textAreaStyle}
          />
          <Pressable onPress={() => void translate()} disabled={busy || !input.trim()} style={buttonStyle}>
            <Text style={{ color: colors.text }}>{busy ? 'Translating…' : 'Translate'}</Text>
          </Pressable>
          <Text selectable style={{ color: result ? colors.text : colors.muted, fontSize: 18, lineHeight: 27 }}>
            {result?.translated_text ?? 'Translation output will appear here.'}
          </Text>
          {result ? <Text style={{ color: colors.muted }}>{result.latency_ms.toFixed(1)} ms · {result.source_language} → {result.target_language}</Text> : null}
        </Card>
      )}

      {directActive ? (
        <>
          {(liveMode === 'full_duplex' || liveMode === 'outbound' || outbound) ? (
            <CaptionCard
              title="Outbound · you → other party"
              source={outbound?.source ?? live?.source_caption ?? ''}
              translation={outbound?.translation ?? live?.translated_caption ?? ''}
            />
          ) : null}
          {(liveMode === 'full_duplex' || liveMode === 'inbound' || inbound) ? (
            <CaptionCard
              title="Inbound · other party → you"
              source={inbound?.source ?? ''}
              translation={inbound?.translation ?? ''}
            />
          ) : null}
        </>
      ) : null}

      {message ? <Text style={{ color: colors.success }}>{message}</Text> : null}
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}

function EngineButton({ title, detail, active, disabled, onPress }: {
  title: string;
  detail: string;
  active: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      disabled={disabled}
      onPress={onPress}
      style={[
        selectionStyle,
        active && { borderColor: colors.accent, backgroundColor: theme.colors.surfaceRaised },
        disabled && { opacity: 0.65 },
      ]}
    >
      <Text style={{ color: colors.text, fontWeight: '700' }}>{active ? '● ' : '○ '}{title}</Text>
      <Text style={{ color: colors.muted }}>{detail}</Text>
    </Pressable>
  );
}

function CaptionCard({ title, source, translation }: { title: string; source: string; translation: string }) {
  return (
    <Card title={title}>
      <Text style={{ color: colors.muted, fontSize: 12 }}>HEARD</Text>
      <Text selectable style={{ color: source ? colors.text : colors.muted, fontSize: 16 }}>{source || 'Waiting for speech…'}</Text>
      <Text style={{ color: colors.muted, fontSize: 12, marginTop: 8 }}>TRANSLATED</Text>
      <Text selectable style={{ color: translation ? colors.text : colors.muted, fontSize: 18, lineHeight: 26 }}>{translation || 'Waiting for translation…'}</Text>
    </Card>
  );
}

function LanguageInput({ label, value, onChange, disabled }: { label: string; value: string; onChange: (value: string) => void; disabled: boolean }) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={{ color: colors.muted, fontSize: 12 }}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        editable={!disabled}
        autoCapitalize="none"
        maxLength={8}
        style={[languageInputStyle, disabled && { opacity: 0.65 }]}
      />
    </View>
  );
}

function ModeButton({ label, value, selected, disabled, onSelect }: {
  label: string;
  value: LiveTranslationMode;
  selected: LiveTranslationMode;
  disabled: boolean;
  onSelect: (value: LiveTranslationMode) => void;
}) {
  return (
    <Pressable
      disabled={disabled}
      onPress={() => onSelect(value)}
      style={[
        buttonStyle,
        selected === value && { borderColor: colors.accent, backgroundColor: theme.colors.surfaceRaised },
        disabled && { opacity: 0.65 },
      ]}
    >
      <Text style={{ color: colors.text }}>{label}</Text>
    </Pressable>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return <Text style={{ color: colors.muted }}><Text style={{ color: colors.text, fontWeight: '600' }}>{label}: </Text>{value}</Text>;
}

const languageInputStyle = {
  color: colors.text,
  borderWidth: 1,
  borderColor: colors.border,
  borderRadius: 8,
  paddingHorizontal: 12,
  paddingVertical: 9,
  minWidth: 90,
} as const;

const textAreaStyle = {
  color: colors.text,
  borderWidth: 1,
  borderColor: colors.border,
  borderRadius: 10,
  minHeight: 140,
  padding: 12,
  textAlignVertical: 'top' as const,
} as const;

const buttonStyle = {
  alignSelf: 'flex-start' as const,
  borderWidth: 1,
  borderColor: colors.border,
  borderRadius: 8,
  paddingHorizontal: 14,
  paddingVertical: 10,
};

const selectionStyle = {
  borderWidth: 1,
  borderColor: colors.border,
  borderRadius: 10,
  padding: 12,
  gap: 4,
};
