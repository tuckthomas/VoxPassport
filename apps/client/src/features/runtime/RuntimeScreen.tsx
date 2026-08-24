import { useEffect, useMemo, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import type {
  DesktopAudioDevice,
  DesktopAudioDeviceRole,
  DesktopAudioStatus,
  NativeAudioRouting,
  NativeAudioRoutingPatch,
  RuntimeStatus,
} from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';
import { colors } from '@/theme';

export default function RuntimeScreen() {
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [audioStatus, setAudioStatus] = useState<DesktopAudioStatus | null>(null);
  const [devices, setDevices] = useState<DesktopAudioDevice[]>([]);
  const [routing, setRouting] = useState<NativeAudioRouting | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function refresh() {
    setError('');
    try {
      const [nextRuntime, nextAudio, nextDevices, nextRouting] = await Promise.all([
        api.status(),
        api.audioStatus(),
        api.audioDevices(),
        api.audioRouting(),
      ]);
      setRuntime(nextRuntime);
      setAudioStatus(nextAudio);
      setDevices(nextDevices.devices ?? []);
      setRouting(nextRouting);
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    }
  }

  useEffect(() => {
    if (target.ready) void refresh();
  }, [target.ready, api]);

  async function updateRouting(patch: NativeAudioRoutingPatch) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      setRouting(await api.updateAudioRouting(patch));
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  async function confirmVirtualMicrophone(confirmed: boolean) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      setRouting(await api.confirmVirtualMicrophone(confirmed));
    } catch (next) {
      setError(next instanceof Error ? next.message : String(next));
    } finally {
      setBusy(false);
    }
  }

  const microphones = useMemo(() => devices.filter((item) => item.role === 'physical_microphone'), [devices]);
  const loopbacks = useMemo(() => devices.filter((item) => item.role === 'loopback_source'), [devices]);
  const renderOutputs = useMemo(() => devices.filter((item) => item.role === 'render_output'), [devices]);

  return (
    <Screen
      title="Runtime & Audio"
      subtitle="Runtime-owned Windows audio routing. Raw PCM stays out of the Expo UI."
      action={<RefreshButton onPress={() => void refresh()} />}
    >
      <Card title="Runtime target" subtitle={`${target.mode} · ${target.activeBaseUrl}`}>
        <StatusLine label="Runtime" value={runtime?.status ?? 'unavailable'} />
        <StatusLine label="Pipeline mode" value={runtime?.mode ?? 'unknown'} />
        <StatusLine label="TTS mode" value={runtime?.tts_mode ?? 'unknown'} />
        <StatusLine label="Languages" value={runtime ? `${runtime.user_language} ↔ ${runtime.remote_language}` : 'unknown'} />
        <StatusLine label="Model residency" value={runtime?.model_residency ?? 'unknown'} />
        <StatusLine label="Models loaded" value={runtime ? (runtime.models_loaded ? 'yes' : 'no') : 'unknown'} />
        {runtime?.translation_strategy ? (
          <StatusLine
            label="Speech strategy"
            value={`${runtime.translation_strategy.strategy_id}${runtime.translation_strategy.transitioning ? ' · switching' : ''}`}
          />
        ) : null}
      </Card>

      <Card title="Native Windows audio helper" subtitle={audioStatus?.note || 'Not probed'}>
        <StatusLine label="Connected" value={audioStatus?.service_connected ? 'yes' : 'no'} />
        <StatusLine label="Device enumeration" value={yesNo(audioStatus?.capabilities.device_enumeration)} />
        <StatusLine label="Microphone capture" value={yesNo(audioStatus?.capabilities.physical_microphone_capture)} />
        <StatusLine label="System loopback" value={yesNo(audioStatus?.capabilities.loopback_capture)} />
        <StatusLine label="Render output" value={yesNo(audioStatus?.capabilities.render_output)} />
        <StatusLine
          label="Native virtual-mic driver"
          value={yesNo(audioStatus?.capabilities.virtual_microphone_output)}
        />
      </Card>

      <EndpointSelector
        title="Physical microphone"
        subtitle="Outbound speech source"
        role="physical_microphone"
        devices={microphones}
        selectedId={routing?.microphone_endpoint_id ?? null}
        disabled={busy}
        onSelect={(id) => void updateRouting({ microphone_endpoint_id: id })}
      />

      <EndpointSelector
        title="Conference/system audio"
        subtitle="WASAPI loopback source. Choose the render endpoint carrying the remote call."
        role="loopback_source"
        devices={loopbacks}
        selectedId={routing?.loopback_endpoint_id ?? null}
        disabled={busy}
        onSelect={(id) => void updateRouting({ loopback_endpoint_id: id })}
      />

      <EndpointSelector
        title="Local translated-audio monitor"
        subtitle="Optional headphones/speaker endpoint for translated inbound audio."
        role="render_output"
        devices={renderOutputs}
        selectedId={routing?.monitor_render_endpoint_id ?? null}
        disabled={busy}
        onSelect={(id) => void updateRouting({ monitor_render_endpoint_id: id })}
      />

      <EndpointSelector
        title="Virtual microphone · render sink"
        subtitle="Select the playback side of an installed virtual-audio pair. VoxPassport writes translated outbound PCM here."
        role="render_output"
        devices={renderOutputs}
        selectedId={routing?.virtual_microphone_render_endpoint_id ?? null}
        disabled={busy}
        onSelect={(id) => void updateRouting({ virtual_microphone_render_endpoint_id: id })}
      />

      <EndpointSelector
        title="Virtual microphone · capture side"
        subtitle="Select the corresponding recording endpoint that Zoom/Meet/Teams will use as its microphone."
        role="physical_microphone"
        devices={microphones}
        selectedId={routing?.virtual_microphone_capture_endpoint_id ?? null}
        disabled={busy}
        onSelect={(id) => void updateRouting({ virtual_microphone_capture_endpoint_id: id })}
      />

      <Card title="Virtual microphone validation">
        <StatusLine label="Pair configured" value={yesNo(routing?.virtual_microphone_configured)} />
        <StatusLine label="Human validated" value={yesNo(routing?.virtual_microphone_validated)} />
        <StatusLine label="Ready" value={yesNo(routing?.virtual_microphone_ready)} />
        <Text style={{ color: colors.muted }}>
          “Configured” only proves both endpoint IDs exist. Mark it validated only after translated audio reaches a real conferencing app through the selected capture endpoint.
        </Text>
        <View style={{ flexDirection: 'row', gap: 10, flexWrap: 'wrap' }}>
          <Pressable
            disabled={busy || !routing?.virtual_microphone_configured}
            onPress={() => void confirmVirtualMicrophone(true)}
            style={buttonStyle}
          >
            <Text style={{ color: colors.text }}>Mark conferencing test passed</Text>
          </Pressable>
          {routing?.virtual_microphone_validated ? (
            <Pressable disabled={busy} onPress={() => void confirmVirtualMicrophone(false)} style={buttonStyle}>
              <Text style={{ color: colors.warning }}>Clear validation</Text>
            </Pressable>
          ) : null}
        </View>
      </Card>

      {runtime ? (
        <Card title="Active model slots">
          {Object.entries(runtime.active_slots ?? {}).map(([slot, model]) => (
            <StatusLine key={slot} label={slot} value={model || 'none'} />
          ))}
          {!Object.keys(runtime.active_slots ?? {}).length ? (
            <Text style={{ color: colors.muted }}>No active slots reported.</Text>
          ) : null}
        </Card>
      ) : null}

      {error ? <Text style={{ color: colors.danger }}>{error}</Text> : null}
    </Screen>
  );
}

function EndpointSelector({
  title,
  subtitle,
  role,
  devices,
  selectedId,
  disabled,
  onSelect,
}: {
  title: string;
  subtitle: string;
  role: DesktopAudioDeviceRole;
  devices: DesktopAudioDevice[];
  selectedId: string | null;
  disabled: boolean;
  onSelect: (id: string | null) => void;
}) {
  return (
    <Card title={title} subtitle={subtitle}>
      {!devices.length ? <Text style={{ color: colors.muted }}>No {role.replaceAll('_', ' ')} endpoints reported.</Text> : null}
      {devices.map((device) => {
        const selected = device.id === selectedId;
        return (
          <Pressable
            key={`${role}:${device.id}`}
            disabled={disabled}
            onPress={() => onSelect(device.id)}
            style={[buttonStyle, selected ? { borderColor: colors.accent } : null]}
          >
            <Text style={{ color: colors.text, fontWeight: selected ? '700' : '500' }}>
              {selected ? '✓ ' : ''}{device.name}{device.is_default ? ' · default' : ''}
            </Text>
            <Text selectable style={{ color: colors.muted, fontSize: 11 }}>{device.id}</Text>
          </Pressable>
        );
      })}
      {selectedId ? (
        <Pressable disabled={disabled} onPress={() => onSelect(null)} style={buttonStyle}>
          <Text style={{ color: colors.muted }}>Clear selection</Text>
        </Pressable>
      ) : null}
    </Card>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <Text style={{ color: colors.muted }}>
      <Text style={{ color: colors.text, fontWeight: '600' }}>{label}: </Text>
      {value}
    </Text>
  );
}

function RefreshButton({ onPress }: { onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={buttonStyle}>
      <Text style={{ color: colors.text }}>Refresh</Text>
    </Pressable>
  );
}

function yesNo(value: boolean | undefined): string {
  return value ? 'yes' : 'no';
}

const buttonStyle = {
  borderWidth: 1,
  borderColor: colors.border,
  borderRadius: 8,
  paddingHorizontal: 12,
  paddingVertical: 8,
  gap: 4,
} as const;
