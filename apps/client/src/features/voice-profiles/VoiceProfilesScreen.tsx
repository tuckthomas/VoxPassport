import { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioPlayerStatus,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import type { ModelEntry, VoiceStageResponse } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { RaisedButton } from '@/components/RaisedButton';
import { Screen } from '@/components/Screen';
import { SelectDropdown } from '@/components/SelectDropdown';
import { AudioFilePicker } from '@/components/AudioFilePicker';
import { colors } from '@/theme';

const DEFAULT_PREVIEW = 'This is a VoxPassport voice preview generated from my enrolled reference voice.';
const REFERENCE_PASSAGE = 'The quick brown fox jumps over the lazy dog near the riverbank. Acoustic speech modeling captures vocal timbre, subtle pitch variations, and natural conversational cadence. By recording this passage with clear articulation, the neural cross-lingual engine learns the exact acoustic signature of your voice for seamless simultaneous translation in meetings and live conferences.';
type AudioSource = 'mic' | 'upload';
const LANGUAGE_NAMES: Record<string, string> = {
  en: 'English (US / UK)', ro: 'Romanian (Română)', es: 'Spanish (Español)', fr: 'French (Français)',
  de: 'German (Deutsch)', it: 'Italian (Italiano)', pt: 'Portuguese (Português)', nl: 'Dutch (Nederlands)',
  pl: 'Polish (Polski)', cs: 'Czech (Čeština)', hu: 'Hungarian (Magyar)', tr: 'Turkish (Türkçe)',
  ru: 'Russian (Русский)', uk: 'Ukrainian (Українська)', bg: 'Bulgarian (Български)', el: 'Greek (Ελληνικά)',
  ar: 'Arabic (العربية)', he: 'Hebrew (עברית)', hi: 'Hindi (हिन्दी)', ja: 'Japanese (日本語)',
  ko: 'Korean (한국어)', zh: 'Chinese (Simplified)', sv: 'Swedish (Svenska)', fi: 'Finnish (Suomi)',
  da: 'Danish (Dansk)', no: 'Norwegian (Norsk)', id: 'Indonesian (Bahasa Indonesia)', vi: 'Vietnamese (Tiếng Việt)',
  th: 'Thai (ไทย)', tl: 'Tagalog', ms: 'Malay (Bahasa Melayu)', fa: 'Persian (فارسی)',
};

export default function VoiceProfilesScreen() {
  const api = useVoxPassportApi();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder, 250);
  const player = useAudioPlayer(null);
  const playerStatus = useAudioPlayerStatus(player);
  const [name, setName] = useState('My Voice Profile');
  const [transcript, setTranscript] = useState('');
  const [refLang, setRefLang] = useState('en');
  const [previewLang, setPreviewLang] = useState('ro');
  const [previewText, setPreviewText] = useState(DEFAULT_PREVIEW);
  const [recordingUri, setRecordingUri] = useState('');
  const [staged, setStaged] = useState<VoiceStageResponse | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [activeTts, setActiveTts] = useState<ModelEntry | null>(null);
  const [audioSource, setAudioSource] = useState<AudioSource>('mic');
  const [uploadedFileName, setUploadedFileName] = useState('');

  const languageOptions = useMemo(() => {
    const advertised = activeTts?.supported_source_languages?.filter((code) => code && code !== '*') || [];
    const codes = advertised.length ? advertised : ['en'];
    return [...new Set(codes.map((code) => code.toLowerCase()))].map((code) => ({
      value: code,
      label: LANGUAGE_NAMES[code] || code,
    }));
  }, [activeTts]);

  useEffect(() => {
    void api.models().then((models) => {
      const model = models.find((entry) => entry.capability === 'TTS' && entry.is_active && entry.voice_cloning_support)
        || models.find((entry) => entry.capability === 'TTS' && entry.is_active)
        || null;
      setActiveTts(model);
    }).catch((next) => setError(next instanceof Error ? next.message : String(next)));
  }, [api]);

  useEffect(() => {
    if (!activeTts) return;
    if (!languageOptions.some((option) => option.value === refLang)) setRefLang(languageOptions[0]?.value || 'en');
    if (!languageOptions.some((option) => option.value === previewLang)) setPreviewLang(languageOptions[0]?.value || 'en');
  }, [activeTts, languageOptions, refLang, previewLang]);

  async function startRecording() {
    setError('');
    setMessage('');
    try {
      const permission = await requestRecordingPermissionsAsync();
      if (!permission.granted) throw new Error('Microphone permission is required to enroll a voice profile.');
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecordingUri('');
      setStaged(null);
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    }
  }

  async function stopRecording() {
    try {
      await recorder.stop();
      setRecordingUri(recorder.uri ?? '');
      await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    }
  }

  async function stageRecording() {
    if (!recordingUri) return;
    setBusy('stage');
    setError('');
    setMessage('');
    try {
      const result = await api.stageVoiceProfile({
        audioUri: recordingUri,
        name: name.trim() || 'My Voice Profile',
        transcript: transcript.trim(),
        refLang: refLang.trim().toLowerCase() || 'en',
        previewLang: previewLang.trim().toLowerCase() || 'ro',
        previewText: previewText.trim() || DEFAULT_PREVIEW,
      });
      setStaged(result);
      if (result.has_preview && result.preview_url) {
        playUrl(result.preview_url);
        setMessage('Reference voice staged and preview generated. Save it when satisfied.');
      } else {
        setMessage(result.preview_error ? `Reference voice staged; preview failed: ${result.preview_error}` : 'Reference voice staged.');
      }
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy('');
    }
  }

  async function commitStage() {
    setBusy('commit');
    setError('');
    setMessage('');
    try {
      const result = await api.commitVoiceStage(name.trim() || staged?.profile_name || 'My Voice Profile');
      if (!result.success) throw new Error(result.error || 'Voice profile could not be saved.');
      setStaged(null);
      setRecordingUri('');
      setMessage('Voice profile saved and activated.');
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy('');
    }
  }

  async function clearStage() {
    setBusy('clear');
    setError('');
    try {
      await api.clearVoiceStage();
      setStaged(null);
      setRecordingUri('');
      setMessage('Staged enrollment cleared.');
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy('');
    }
  }

  function playUrl(path: string) {
    if (playerStatus.playing) {
      player.pause();
      void player.seekTo(0);
      return;
    }
    player.replace(api.mediaUrl(path));
    player.play();
  }

  return (
    <Screen
      title="Voice Profile Studio"
      subtitle="Create and manage the reference voices used by the live translation engine."
    >
      <View style={styles.studioPanel}>
        <View style={styles.panelHeader}>
          <View style={styles.headerTitleRow}><Text style={styles.panelTitle}>Create Voice Profile</Text><Text style={styles.enrollmentBadge}>ENROLLMENT</Text></View>
          <Text style={styles.headerHint}>Universal Reference Audio & Speaker Timbre</Text>
        </View>

        <View style={styles.panelBody}>
          <View style={styles.twoColumn}>
            <View style={styles.field}><Text style={styles.label}>PROFILE NAME</Text><TextInput value={name} onChangeText={setName} placeholder="e.g. Presentation Voice, Conference Studio…" placeholderTextColor="#697589" style={styles.input} /></View>
            <View style={styles.field}><Text style={styles.label}>REFERENCE PASSAGE LANGUAGE</Text><SelectDropdown label="Reference passage language" value={refLang} options={languageOptions} onChange={setRefLang} /></View>
          </View>

          <View style={styles.audioSourceGroup}>
            <Text style={styles.sectionLabel}>Audio Source</Text>
            <View accessibilityRole="radiogroup" style={styles.sourceSelector}>
              <SourceTab label="♩  Record Microphone Sample" selected={audioSource === 'mic'} onPress={() => setAudioSource('mic')} />
              <SourceTab label="▣  Upload Reference Audio File" selected={audioSource === 'upload'} onPress={() => setAudioSource('upload')} />
            </View>
          </View>

          {audioSource === 'mic' ? <View style={styles.sourcePanel}>
            <Text style={styles.sectionLabel}>Phonetic Reference Passage (Read aloud while recording)</Text>
            <View style={styles.passage}><Text style={styles.passageText}>“{transcript || REFERENCE_PASSAGE}”</Text></View>
            {!recorderState.isRecording ? (
              <RaisedButton label="♩  START RECORDING" disabled={Boolean(busy)} backgroundColor="#234f9e" onPress={() => void startRecording()} />
            ) : (
              <RaisedButton label={`■  STOP RECORDING · ${(recorderState.durationMillis / 1000).toFixed(1)}s`} backgroundColor="#b23b42" onPress={() => void stopRecording()} />
            )}
          </View> : <View style={styles.sourcePanel}>
            <AudioFilePicker onSelect={(uri, fileName) => { setRecordingUri(uri); setUploadedFileName(fileName); setStaged(null); setMessage(''); setError(''); }} />
            {uploadedFileName ? <Text style={styles.selectedFile}>Selected: {uploadedFileName}</Text> : null}
          </View>}

          <View style={styles.previewPanel}>
            <View style={styles.previewHeading}><Text style={styles.previewTitle}>Cloned Voice Output Preview</Text><Text style={styles.enrollmentBadge}>TARGET SYNTHESIS</Text></View>
            <View style={styles.twoColumn}>
              <View style={[styles.field, styles.previewField]}><Text style={styles.label}>OUTPUT LANGUAGE</Text><SelectDropdown label="Output language" value={previewLang} options={languageOptions} onChange={setPreviewLang} /></View>
              <View style={styles.previewActions}>
          {recordingUri && !staged ? (
            <RaisedButton label={busy === 'stage' ? 'Generating preview…' : 'Stage & preview'} disabled={Boolean(busy)} onPress={() => void stageRecording()} />
          ) : null}
          {staged ? (
            <>
              {staged.preview_url ? <RaisedButton label="Play staged preview" latched={playerStatus.playing} onPress={() => playUrl(`${staged.preview_url}?t=${Date.now()}`)} /> : null}
              <RaisedButton label={busy === 'commit' ? 'Saving…' : 'Save & activate'} disabled={Boolean(busy)} backgroundColor="#059669" onPress={() => void commitStage()} />
              <RaisedButton label="Discard" backgroundColor="#dc4f57" disabled={Boolean(busy)} onPress={() => void clearStage()} />
            </>
          ) : null}
              </View>
            </View>
            <TextInput value={previewText} onChangeText={setPreviewText} multiline placeholder="Preview text" placeholderTextColor="#697589" style={styles.previewTextInput} />
          </View>

          <View style={styles.bottomBar}>
            <View><Text style={styles.engineBadge}>{activeTts?.name || 'Active voice-cloning model'}</Text><Text style={styles.engineHint}>Languages supplied by active model metadata</Text></View>
            <View style={styles.bottomActions}>{staged ? <RaisedButton label={busy === 'commit' ? 'Saving…' : 'Save & activate'} disabled={Boolean(busy)} backgroundColor="#059669" onPress={() => void commitStage()} /> : <Text style={styles.readyHint}>RECORD A SAMPLE TO CONTINUE</Text>}</View>
          </View>
        </View>
        {recordingUri && !staged ? <Text style={{ color: colors.success }}>Reference recording ready for preview.</Text> : null}
      </View>

      {message ? <Text style={{ color: colors.success }}>{message}</Text> : null}
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}

function SourceTab({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const [hovered, setHovered] = useState(false);
  return <Pressable
    accessibilityRole="radio"
    accessibilityState={{ checked: selected }}
    onHoverIn={() => setHovered(true)}
    onHoverOut={() => setHovered(false)}
    onPress={onPress}
    style={[styles.sourceTab, hovered && !selected && styles.sourceTabHovered, selected && styles.sourceTabSelected]}
  >
    <Text style={[styles.sourceTabText, hovered && !selected && styles.sourceTabTextHovered, selected && styles.sourceTabTextSelected]}>{label}</Text>
  </Pressable>;
}

const styles = StyleSheet.create({
  studioPanel: { backgroundColor: '#0d1420', borderWidth: 1, borderColor: '#26354a', borderRadius: 15, overflow: 'hidden' },
  panelHeader: { minHeight: 48, paddingHorizontal: 18, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: '#26354a', gap: 8 },
  headerTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  panelTitle: { color: '#f7f9fc', fontSize: 16, fontWeight: '800' },
  enrollmentBadge: { color: '#5ea8ff', backgroundColor: '#122441', borderWidth: 1, borderColor: '#285080', borderRadius: 3, paddingHorizontal: 8, paddingVertical: 3, fontSize: 13, fontWeight: '800' },
  headerHint: { color: '#59667a', fontSize: 13 },
  panelBody: { padding: 18, gap: 14 },
  twoColumn: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  field: { minWidth: 260, flex: 1, gap: 7 },
  label: { color: '#73b2ff', fontSize: 13, fontWeight: '800' },
  input: { minHeight: 44, color: '#e9eef7', backgroundColor: '#09101a', borderWidth: 1, borderColor: '#283a55', borderRadius: 8, paddingHorizontal: 13, fontSize: 14 },
  sectionLabel: { color: '#d8dfeb', fontSize: 16, marginTop: 2 },
  audioSourceGroup: { gap: 6 },
  sourceSelector: { flexDirection: 'row', gap: 6, padding: 4, backgroundColor: '#0b0f19', borderWidth: 1, borderColor: 'rgba(59,130,246,.25)', borderRadius: 6 },
  sourceTab: { flex: 1, minHeight: 36, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 12, paddingVertical: 8, backgroundColor: 'transparent', borderWidth: 1, borderColor: 'transparent', borderRadius: 4 },
  sourceTabHovered: { backgroundColor: 'rgba(37,99,235,.15)' },
  sourceTabSelected: { backgroundColor: '#1d4ed8', borderColor: '#3b82f6', boxShadow: 'inset 0 2px 4px rgba(0,0,0,.4)' },
  sourceTabText: { color: '#93c5fd', fontSize: 13, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.48, textAlign: 'center' },
  sourceTabTextHovered: { color: '#ffffff' },
  sourceTabTextSelected: { color: '#ffffff' },
  sourcePanel: { gap: 14 },
  selectedFile: { color: '#93c5fd', fontSize: 13, fontWeight: '600' },
  passage: { backgroundColor: '#09101a', borderWidth: 1, borderColor: '#28384f', borderRadius: 10, padding: 20 },
  passageText: { color: '#f0f3f8', fontSize: 15, lineHeight: 24, fontWeight: '600' },
  previewPanel: { backgroundColor: '#09101a', borderWidth: 1, borderColor: '#28384f', borderRadius: 10, padding: 16, gap: 12 },
  previewHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  previewTitle: { color: '#62a8ff', fontSize: 17, fontWeight: '800' },
  previewField: { flexGrow: 1 },
  previewActions: { minWidth: 180, justifyContent: 'flex-end', flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-end', gap: 8 },
  previewTextInput: { minHeight: 76, color: '#e9eef7', backgroundColor: '#0d1522', borderWidth: 1, borderColor: '#283a55', borderRadius: 8, padding: 12, textAlignVertical: 'top' },
  bottomBar: { borderTopWidth: 1, borderTopColor: '#26354a', paddingTop: 14, flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  engineBadge: { color: '#62a8ff', backgroundColor: '#122441', borderWidth: 1, borderColor: '#285080', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 4, fontFamily: 'monospace', fontSize: 13, fontWeight: '700' },
  engineHint: { color: '#5f6c7e', fontSize: 13, marginTop: 4 },
  bottomActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  readyHint: { color: '#64748b', fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
});
