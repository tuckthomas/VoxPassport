import { useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { colors } from '@/theme';
import {
  getDesktopAudioCapabilities,
  getDesktopRuntimeStatus,
  startDesktopRuntime,
  stopDesktopRuntime,
  type DesktopAudioCapabilities,
  type DesktopRuntimeProcessStatus,
} from '@/desktop/bridge';

export default function RuntimeScreen() {
  const [audio, setAudio] = useState<DesktopAudioCapabilities | null>(null);
  const [runtime, setRuntime] = useState<DesktopRuntimeProcessStatus | null>(null);
  const [error, setError] = useState('');

  async function refresh() {
    setError('');
    try {
      const [audioState, runtimeState] = await Promise.all([
        getDesktopAudioCapabilities(),
        getDesktopRuntimeStatus(),
      ]);
      setAudio(audioState);
      setRuntime(runtimeState);
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function changeRuntime(action: 'start' | 'stop') {
    try {
      const state = action === 'start' ? await startDesktopRuntime() : await stopDesktopRuntime();
      setRuntime(state);
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    }
  }

  return (
    <Screen title="Runtime & Audio" subtitle="Native desktop capability state. Realtime PCM never crosses the React/Tauri UI bridge.">
      <Card>
        <Text style={{ color: colors.text, fontWeight: '700' }}>Local runtime</Text>
        <Text style={{ color: colors.muted, marginTop: 8 }}>
          {runtime ? `${runtime.running ? 'Running' : 'Stopped'}${runtime.pid ? ` · PID ${runtime.pid}` : ''}` : 'Browser/PWA mode or desktop state unavailable'}
        </Text>
        {runtime?.base_url ? <Text style={{ color: colors.muted, marginTop: 4 }}>{runtime.base_url}</Text> : null}
        <View style={{ flexDirection: 'row', gap: 10, marginTop: 14 }}>
          <Action label="Start" onPress={() => void changeRuntime('start')} />
          <Action label="Stop" onPress={() => void changeRuntime('stop')} />
          <Action label="Refresh" onPress={() => void refresh()} />
        </View>
      </Card>
      <Card>
        <Text style={{ color: colors.text, fontWeight: '700' }}>Desktop audio</Text>
        <Text style={{ color: colors.muted, marginTop: 8 }}>Platform: {audio?.platform ?? 'web / unavailable'}</Text>
        <Text style={{ color: colors.muted }}>Physical microphone: {audio?.physical_microphone ? 'available' : 'not reported'}</Text>
        <Text style={{ color: colors.muted }}>Loopback capture: {audio?.loopback_capture ? 'available' : 'not reported'}</Text>
        <Text style={{ color: colors.muted }}>Virtual microphone output: {audio?.virtual_microphone_output ? 'available' : 'not yet validated'}</Text>
        {audio?.virtual_microphone_note ? <Text style={{ color: colors.muted, marginTop: 6 }}>{audio.virtual_microphone_note}</Text> : null}
      </Card>
      {error ? <Text style={{ color: '#fca5a5' }}>{error}</Text> : null}
    </Screen>
  );
}

function Action({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={{ borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 }}>
      <Text style={{ color: colors.text }}>{label}</Text>
    </Pressable>
  );
}
