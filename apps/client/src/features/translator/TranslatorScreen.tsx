import { useEffect, useMemo, useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { VoxPassportApi } from '@/api/client';
import type { LanguageConfiguration, TranslationResponse } from '@/api/contracts';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { colors } from '@/theme';

export default function TranslatorScreen() {
  const target = useRuntimeTarget();
  const api = useMemo(
    () => new VoxPassportApi(target.activeBaseUrl, { nativeLocal: target.mode === 'local' }),
    [target.activeBaseUrl, target.mode],
  );
  const [languages, setLanguages] = useState<LanguageConfiguration | null>(null);
  const [source, setSource] = useState('en');
  const [destination, setDestination] = useState('ro');
  const [input, setInput] = useState('');
  const [result, setResult] = useState<TranslationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!target.ready) return;
    api.languages().then((configuration) => {
      setLanguages(configuration);
      setSource(configuration.user_language || 'en');
      setDestination(configuration.remote_language || 'ro');
    }).catch((next) => setError(next instanceof Error ? next.message : String(next)));
  }, [api, target.ready]);

  async function translate() {
    if (!input.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      setResult(await api.translate(input.trim(), source.trim().toLowerCase(), destination.trim().toLowerCase()));
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  function swapLanguages() {
    setSource(destination);
    setDestination(source);
    if (result) {
      setInput(result.translated_text);
      setResult(null);
    }
  }

  return (
    <Screen
      title="Translator"
      subtitle={`Text workflow through ${target.mode}: ${target.activeBaseUrl}. Live native audio is the next desktop stage.`}
    >
      <Card title="Language pair" subtitle={languages ? `${languages.supported.length} runtime language codes reported` : 'Loading runtime languages…'}>
        <View style={{ flexDirection: 'row', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <LanguageInput label="From" value={source} onChange={setSource} />
          <Pressable onPress={swapLanguages} style={buttonStyle}>
            <Text style={{ color: colors.text }}>Swap</Text>
          </Pressable>
          <LanguageInput label="To" value={destination} onChange={setDestination} />
        </View>
      </Card>

      <Card title="Source text">
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
      </Card>

      <Card title="Translation" subtitle={result ? `${result.latency_ms.toFixed(1)} ms · ${result.source_language} → ${result.target_language}` : undefined}>
        <Text selectable style={{ color: result ? colors.text : colors.muted, fontSize: 18, lineHeight: 27 }}>
          {result?.translated_text ?? 'Translation output will appear here.'}
        </Text>
      </Card>

      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}

function LanguageInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={{ color: colors.muted, fontSize: 12 }}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        autoCapitalize="none"
        maxLength={8}
        style={languageInputStyle}
      />
    </View>
  );
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
