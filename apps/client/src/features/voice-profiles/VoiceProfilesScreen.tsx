import { useEffect, useState } from 'react';
import { Text, TextInput, View } from 'react-native';
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
      title="Voice Profiles"
      subtitle="Enroll a reference voice, preview cloned speech, and select the active voice independently from the TTS engine."
      action={<ActionButton label="Refresh" onPress={() => void refresh()} />}
    >
      <Card title="Enroll a voice" subtitle="Record a reference sample, generate a translated preview, then explicitly save it.">
        <TextInput value={name} onChangeText={setName} placeholder="Profile name" placeholderTextColor={colors.muted} style={inputStyle} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          <TextInput value={refLang} onChangeText={setRefLang} autoCapitalize="none" placeholder="Reference language" placeholderTextColor={colors.muted} style={shortInputStyle} />
          <TextInput value={previewLang} onChangeText={setPreviewLang} autoCapitalize="none" placeholder="Preview language" placeholderTextColor={colors.muted} style={shortInputStyle} />
        </View>
        <TextInput
          value={transcript}
          onChangeText={setTranscript}
          multiline
          placeholder="Exact reference transcript (required by some cloning engines)"
          placeholderTextColor={colors.muted}
          style={textAreaStyle}
        />
        <TextInput
          value={previewText}
          onChangeText={setPreviewText}
          multiline
          placeholder="Preview text"
          placeholderTextColor={colors.muted}
          style={textAreaStyle}
        />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {!recorderState.isRecording ? (
            <ActionButton label="Record reference" disabled={Boolean(busy)} onPress={() => void startRecording()} />
          ) : (
            <ActionButton label="Stop recording" destructive onPress={() => void stopRecording()} />
          )}
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
        {recorderState.isRecording ? <Text style={{ color: colors.muted }}>Recording: {(recorderState.durationMillis / 1000).toFixed(1)} seconds</Text> : null}
        {recordingUri && !staged ? <Text style={{ color: colors.success }}>Reference recording ready for preview.</Text> : null}
      </Card>

      <Card title="Preview settings" subtitle="These settings are also used when regenerating a preview for an existing profile.">
        <Text style={{ color: colors.muted }}>Target language: {previewLang || 'ro'}</Text>
        <Text style={{ color: colors.muted }}>{previewText || DEFAULT_PREVIEW}</Text>
      </Card>

      {profiles.map((profile) => (
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
      ))}
      {!profiles.length && !error ? <Text style={{ color: colors.muted }}>No saved voice profiles.</Text> : null}
      {message ? <Text style={{ color: colors.success }}>{message}</Text> : null}
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}

const inputStyle = {
  color: colors.text,
  borderWidth: 1,
  borderColor: colors.border,
  borderRadius: 8,
  paddingHorizontal: 12,
  paddingVertical: 10,
} as const;

const shortInputStyle = {
  ...inputStyle,
  minWidth: 150,
  flexGrow: 1,
} as const;

const textAreaStyle = {
  ...inputStyle,
  minHeight: 90,
  textAlignVertical: 'top' as const,
} as const;
