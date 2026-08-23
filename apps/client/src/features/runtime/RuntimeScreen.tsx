import { useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { colors } from '@/theme';
import {
  getDesktopAudioCapabilities,
  getDesktopAudioDevices,
  getDesktopRuntimeStatus,
  startDesktopRuntime,
  stopDesktopRuntime,
  type DesktopAudioCapabilities,
  type DesktopAudioDevice,
  type DesktopRuntimeProcessStatus,
} from '@/desktop/bridge';

export default function RuntimeScreen() {
  const [audio, setAudio] = useState<DesktopAudioCapabilities | null>(null);
  const [devices, setDevices] = useState<DesktopAudioDevice[]>([]);
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
      if (audioState?.microphone_enumeration || audioState?.render_enumeration) {
        setDevices((await getDesktopAudioDevices()) ?? []);
      } else {
        setDevices([]);
      }
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

  const microphones = devices.filter((device) => device.role === 'physical_microphone');
  const renderDevices = devices.filter((device) => device.role === 'render_output');

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
        <Text style={{ color: colors.text, fontWeight: '700' }}>Desktop audio implementation</Text>
        <Text style={{ color: colors.muted, marginTop: 8 }}>Platform: {audio?.platform ?? 'web / unavailable'}</Text>
        <Capability label="Native platform boundary" ready={audio?.native_audio_boundary} />
        <Capability label="Microphone enumeration" ready={audio?.microphone_enumeration} />
        <Capability label="Microphone capture" ready={audio?.microphone_capture} />
        <Capability label="Render-device enumeration" ready={audio?.render_enumeration} />
        <Capability label="Loopback capture" ready={audio?.loopback_capture} />
        <Capability label="Virtual microphone output" ready={audio?.virtual_microphone_output} />
        {audio?.note ? <Text style={{ color: colors.muted, marginTop: 6 }}>{audio.note}</Text> : null}
      </Card>
      <DeviceList title="Capture endpoints" devices={microphones} />
      <DeviceList title="Render endpoints" devices={renderDevices} />
      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}

function DeviceList({ title, devices }: { title: string; devices: DesktopAudioDevice[] }) {
  return (
    <Card>
      <Text style={{ color: colors.text, fontWeight: '700' }}>{title}</Text>
      {devices.length ? devices.map((device) => (
        <View key={device.id} style={{ gap: 2 }}>
          <Text style={{ color: colors.text }}>{device.name}{device.is_default ? ' · Default' : ''}</Text>
          <Text selectable style={{ color: colors.muted, fontSize: 12 }}>{device.id}</Text>
        </View>
      )) : <Text style={{ color: colors.muted }}>No endpoints reported.</Text>}
    </Card>
  );
}

function Capability({ label, ready }: { label: string; ready?: boolean }) {
  return <Text style={{ color: ready ? colors.success : colors.muted }}>{label}: {ready ? 'implemented' : 'not yet implemented/validated'}</Text>;
}

function Action({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={{ borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 }}>
      <Text style={{ color: colors.text }}>{label}</Text>
    </Pressable>
  );
}
