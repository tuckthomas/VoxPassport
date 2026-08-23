import { useEffect, useState } from 'react';
import { Text } from 'react-native';
import type { VoiceProfile } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { ActionButton, Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { colors } from '@/theme';

export default function VoiceProfilesScreen() {
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [error, setError] = useState('');

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

  return (
    <Screen
      title="Voice Profiles"
      subtitle="Voice identity stays separate from the selected TTS/provider implementation."
      action={<ActionButton label="Refresh" onPress={() => void refresh()} />}
    >
      {profiles.map((profile) => (
        <Card
          key={profile.profile_id}
          title={profile.profile_name}
          subtitle={profile.is_active ? 'Active profile' : profile.status}
        >
          <Text style={{ color: colors.muted }}>
            Reference language: {profile.ref_lang ?? 'unknown'}
          </Text>
          <Text style={{ color: colors.muted }}>
            Reference audio: {profile.has_audio ? 'available' : 'missing'}
          </Text>
          <Text style={{ color: colors.muted }}>
            Translated preview: {profile.has_translation_audio ? 'available' : 'not generated'}
          </Text>
        </Card>
      ))}
      {!profiles.length && !error ? (
        <Text style={{ color: colors.muted }}>No saved voice profiles.</Text>
      ) : null}
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}
