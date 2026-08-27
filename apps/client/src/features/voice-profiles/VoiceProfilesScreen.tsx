import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import type { VoiceProfile, VoiceStageResponse } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { ActionButton, Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { colors } from '@/theme';

const DEFAULT_PREVIEW = 'This is a VoxPassport voice preview generated from my enrolled reference voice.';
const REFERENCE_PASSAGE = 'The quick brown fox jumps over the lazy dog near the riverbank. Acoustic speech modeling captures vocal timbre, subtle pitch variations, and natural conversational cadence. By recording this passage with clear articulation, the neural cross-lingual engine learns the exact acoustic signature of your voice for seamless simultaneous translation in meetings and live conferences.';

export default function VoiceProfilesScreen() {
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder, 250);
  const player = useAudioPlayer(null);
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
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

  async function refresh() {
    setError('');
    try {
      setProfiles((await api.voiceProfiles()).profiles);
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    }
  }

  useEffect(() => {
    if (target.ready) void refresh();
  }, [target.ready, api]);

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
      await refresh();
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

  async function activate(profile: VoiceProfile) {
    setBusy(profile.profile_id);
    setError('');
    setMessage('');
    try {
      const result = await api.activateVoiceProfile(profile.profile_id);
      if (!result.success) throw new Error(result.error || 'Voice profile activation failed.');
      setMessage(`${profile.profile_name} is now active.`);
      await refresh();
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy('');
    }
  }

  async function generatePreview(profile: VoiceProfile) {
    setBusy(profile.profile_id);
    setError('');
    setMessage('');
    try {
      await api.synthesizeVoicePreview(
        profile.profile_id,
        previewText.trim() || DEFAULT_PREVIEW,
        previewLang.trim().toLowerCase() || 'ro',
      );
      playUrl(`/api/voice/translation/${encodeURIComponent(profile.profile_id)}?t=${Date.now()}`);
      setMessage(`Generated a new preview for ${profile.profile_name}.`);
      await refresh();
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy('');
    }
  }

  async function remove(profile: VoiceProfile) {
    setBusy(profile.profile_id);
    setError('');
    setMessage('');
    try {
      const result = await api.deleteVoiceProfile(profile.profile_id);
      if (!result.success) throw new Error(result.error || 'Voice profile deletion failed.');
      setMessage(`${profile.profile_name} was deleted.`);
      await refresh();
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy('');
    }
  }

  function playUrl(path: string) {
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
            <View style={styles.field}><Text style={styles.label}>REFERENCE PASSAGE LANGUAGE</Text><TextInput value={refLang} onChangeText={setRefLang} autoCapitalize="none" placeholder="English (US / UK)" placeholderTextColor="#697589" style={styles.input} /></View>
          </View>

          <Text style={styles.sectionLabel}>Audio Source</Text>
          <View style={styles.sourceSelector}>
            <Pressable style={[styles.sourceOption, styles.sourceOptionActive]} onPress={() => void startRecording()}><Text style={styles.sourceActiveText}>♩  RECORD MICROPHONE SAMPLE</Text></Pressable>
            <Pressable style={styles.sourceOption}><Text style={styles.sourceText}>▣  UPLOAD REFERENCE AUDIO FILE</Text></Pressable>
          </View>

          <Text style={styles.sectionLabel}>Phonetic Reference Passage (Read aloud while recording)</Text>
          <View style={styles.passage}><Text style={styles.passageText}>“{transcript || REFERENCE_PASSAGE}”</Text></View>

          {!recorderState.isRecording ? (
            <Pressable disabled={Boolean(busy)} onPress={() => void startRecording()} style={[styles.recordButton, Boolean(busy) && styles.disabled]}><Text style={styles.recordButtonText}>♩  START RECORDING</Text></Pressable>
          ) : (
            <Pressable onPress={() => void stopRecording()} style={[styles.recordButton, styles.stopButton]}><Text style={styles.recordButtonText}>■  STOP RECORDING · {(recorderState.durationMillis / 1000).toFixed(1)}s</Text></Pressable>
          )}

          <View style={styles.previewPanel}>
            <View style={styles.previewHeading}><Text style={styles.previewTitle}>Cloned Voice Output Preview</Text><Text style={styles.enrollmentBadge}>TARGET SYNTHESIS</Text></View>
            <View style={styles.twoColumn}>
              <View style={[styles.field, styles.previewField]}><Text style={styles.label}>OUTPUT LANGUAGE</Text><TextInput value={previewLang} onChangeText={setPreviewLang} autoCapitalize="none" placeholder="Romanian (Română)" placeholderTextColor="#697589" style={styles.input} /></View>
              <View style={styles.previewActions}>
          {recordingUri && !staged ? (
            <ActionButton label={busy === 'stage' ? 'Generating preview…' : 'Stage & preview'} disabled={Boolean(busy)} onPress={() => void stageRecording()} />
          ) : null}
          {staged ? (
            <>
              {staged.preview_url ? <ActionButton label="Play staged preview" onPress={() => playUrl(`${staged.preview_url}?t=${Date.now()}`)} /> : null}
              <ActionButton label={busy === 'commit' ? 'Saving…' : 'Save & activate'} disabled={Boolean(busy)} onPress={() => void commitStage()} />
              <ActionButton label="Discard" destructive disabled={Boolean(busy)} onPress={() => void clearStage()} />
            </>
          ) : null}
              </View>
            </View>
            <TextInput value={previewText} onChangeText={setPreviewText} multiline placeholder="Preview text" placeholderTextColor="#697589" style={styles.previewTextInput} />
          </View>

          <View style={styles.bottomBar}>
            <View><Text style={styles.engineBadge}>Higgs Q4 Native Voice Clone</Text><Text style={styles.engineHint}>5s GPU-conditioned reference window</Text></View>
            <View style={styles.bottomActions}><ActionButton label="Refresh profiles" onPress={() => void refresh()} />{staged ? <ActionButton label={busy === 'commit' ? 'Saving…' : 'Save & activate'} disabled={Boolean(busy)} onPress={() => void commitStage()} /> : null}</View>
          </View>
        </View>
        {recordingUri && !staged ? <Text style={{ color: colors.success }}>Reference recording ready for preview.</Text> : null}
      </View>

      <View style={styles.savedHeader}><Text style={styles.savedTitle}>Saved Voice Profiles</Text><Text style={styles.savedCount}>{profiles.length} AVAILABLE</Text></View>
      <View style={styles.profileGrid}>{profiles.map((profile) => (
        <Card
          key={profile.profile_id}
          title={profile.profile_name}
          subtitle={profile.is_active ? 'Active profile' : profile.status}
        >
          <Text style={{ color: colors.muted }}>Reference language: {profile.ref_lang ?? 'unknown'}</Text>
          <Text style={{ color: colors.muted }}>Reference audio: {profile.has_audio ? 'available' : 'missing'}</Text>
          <Text style={{ color: colors.muted }}>Translated preview: {profile.has_translation_audio ? 'available' : 'not generated'}</Text>
          {profile.last_preview_model ? <Text style={{ color: colors.muted }}>Last preview engine: {profile.last_preview_model}</Text> : null}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {profile.has_audio ? <ActionButton label="Play reference" onPress={() => playUrl(`/api/voice/audio/${encodeURIComponent(profile.profile_id)}?t=${Date.now()}`)} /> : null}
            {profile.has_translation_audio ? <ActionButton label="Play preview" onPress={() => playUrl(`/api/voice/translation/${encodeURIComponent(profile.profile_id)}?t=${Date.now()}`)} /> : null}
            <ActionButton label={busy === profile.profile_id ? 'Working…' : 'Generate preview'} disabled={Boolean(busy)} onPress={() => void generatePreview(profile)} />
            {!profile.is_active ? <ActionButton label="Activate" disabled={Boolean(busy)} onPress={() => void activate(profile)} /> : null}
            <ActionButton label="Delete" destructive disabled={Boolean(busy)} onPress={() => void remove(profile)} />
          </View>
        </Card>
      ))}</View>
      {!profiles.length && !error ? <Text style={{ color: colors.muted }}>No saved voice profiles.</Text> : null}
      {message ? <Text style={{ color: colors.success }}>{message}</Text> : null}
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  studioPanel: { backgroundColor: '#0d1420', borderWidth: 1, borderColor: '#26354a', borderRadius: 15, overflow: 'hidden' },
  panelHeader: { minHeight: 48, paddingHorizontal: 18, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: '#26354a', gap: 8 },
  headerTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  panelTitle: { color: '#f7f9fc', fontSize: 16, fontWeight: '800' },
  enrollmentBadge: { color: '#5ea8ff', backgroundColor: '#122441', borderWidth: 1, borderColor: '#285080', borderRadius: 3, paddingHorizontal: 8, paddingVertical: 3, fontSize: 11, fontWeight: '800' },
  headerHint: { color: '#59667a', fontSize: 12 },
  panelBody: { padding: 18, gap: 14 },
  twoColumn: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  field: { minWidth: 260, flex: 1, gap: 7 },
  label: { color: '#73b2ff', fontSize: 12, fontWeight: '800' },
  input: { minHeight: 44, color: '#e9eef7', backgroundColor: '#09101a', borderWidth: 1, borderColor: '#283a55', borderRadius: 8, paddingHorizontal: 13, fontSize: 14 },
  sectionLabel: { color: '#d8dfeb', fontSize: 16, marginTop: 2 },
  sourceSelector: { flexDirection: 'row', borderWidth: 1, borderColor: '#263957', borderRadius: 6, overflow: 'hidden', backgroundColor: '#09101b' },
  sourceOption: { width: '50%', minHeight: 42, alignItems: 'center', justifyContent: 'center' },
  sourceOptionActive: { backgroundColor: '#245be0', borderWidth: 1, borderColor: '#3c8aff', borderRadius: 5 },
  sourceActiveText: { color: '#fff', fontSize: 13, fontWeight: '800' },
  sourceText: { color: '#8bb9f3', fontSize: 13, fontWeight: '800' },
  passage: { backgroundColor: '#09101a', borderWidth: 1, borderColor: '#28384f', borderRadius: 10, padding: 20 },
  passageText: { color: '#f0f3f8', fontSize: 15, lineHeight: 24, fontWeight: '600' },
  recordButton: { minHeight: 52, alignItems: 'center', justifyContent: 'center', backgroundColor: '#23468d', borderWidth: 1, borderColor: '#2d5bab', borderRadius: 4 },
  stopButton: { backgroundColor: '#a83136', borderColor: '#d54b52' },
  recordButtonText: { color: '#dbe5f7', fontSize: 14, fontWeight: '800' },
  disabled: { opacity: 0.5 },
  previewPanel: { backgroundColor: '#09101a', borderWidth: 1, borderColor: '#28384f', borderRadius: 10, padding: 16, gap: 12 },
  previewHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  previewTitle: { color: '#62a8ff', fontSize: 17, fontWeight: '800' },
  previewField: { flexGrow: 1 },
  previewActions: { minWidth: 180, justifyContent: 'flex-end', flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-end', gap: 8 },
  previewTextInput: { minHeight: 76, color: '#e9eef7', backgroundColor: '#0d1522', borderWidth: 1, borderColor: '#283a55', borderRadius: 8, padding: 12, textAlignVertical: 'top' },
  bottomBar: { borderTopWidth: 1, borderTopColor: '#26354a', paddingTop: 14, flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  engineBadge: { color: '#62a8ff', backgroundColor: '#122441', borderWidth: 1, borderColor: '#285080', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 4, fontFamily: 'monospace', fontSize: 12, fontWeight: '700' },
  engineHint: { color: '#5f6c7e', fontSize: 12, marginTop: 4 },
  bottomActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  savedHeader: { marginTop: 6, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  savedTitle: { color: '#eff3f8', fontSize: 18, fontWeight: '800' },
  savedCount: { color: '#6daeff', fontSize: 12, fontWeight: '800' },
  profileGrid: { gap: 12 },
});
