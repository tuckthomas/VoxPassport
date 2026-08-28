import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import type { ResourceSnapshot } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { StatusLight } from '@/components/StatusLight';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';

export function ResourceMonitor() {
  const api = useVoxPassportApi();
  const target = useRuntimeTarget();
  const { width } = useWindowDimensions();
  const [snapshot, setSnapshot] = useState<ResourceSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [collapsed, setCollapsed] = useState(() => readStoredBoolean('voxpassport.resourceMonitor.collapsed', false));
  const [enabled, setEnabled] = useState(() => readStoredBoolean('voxpassport.resourceMonitor.enabled', true));

  useEffect(() => {
    if (!enabled || !target.ready) return;
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const refresh = async () => {
      try {
        const next = await api.resources();
        if (!cancelled) { setSnapshot(next); setConnected(true); }
      } catch {
        if (!cancelled) setConnected(false);
      }
    };
    void refresh();
    timer = setInterval(() => void refresh(), 2000);
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [api, enabled, target.ready]);

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    storeBoolean('voxpassport.resourceMonitor.collapsed', next);
  }

  function toggleEnabled() {
    const next = !enabled;
    setEnabled(next);
    setConnected(false);
    storeBoolean('voxpassport.resourceMonitor.enabled', next);
  }

  const gpu = snapshot?.gpu;
  const cpu = snapshot?.cpu;
  const memory = snapshot?.memory;
  const compact = collapsed || width < 920;

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Pressable accessibilityRole="switch" accessibilityState={{ checked: enabled }} accessibilityLabel={enabled ? 'Disable resource monitor' : 'Enable resource monitor'} onPress={toggleEnabled} style={[styles.power, enabled && styles.powerOn]}><Text style={styles.powerText}>◉</Text></Pressable>
          <Text style={styles.monitorIcon}>▣</Text><Text style={styles.title}>SYSTEM RESOURCE MONITOR</Text>
        </View>
        <View style={styles.headerRight}>
          {compact && enabled ? <Text style={styles.compactReadings}>{formatCompact(gpu, cpu?.usage_percent, memory)}</Text> : null}
          <StatusLight tone={connected && enabled ? 'green' : 'off'} size={6} />
          <Text style={styles.status}>{enabled ? (connected ? 'Live' : 'Connecting') : 'Off'}</Text>
          <Pressable accessibilityRole="switch" accessibilityState={{ expanded: !compact }} accessibilityLabel={compact ? 'Expand resource monitor' : 'Minimize resource monitor'} onPress={toggleCollapsed} style={styles.collapse}><Text style={styles.collapseText}>{compact ? '⌃' : '⌄'}</Text></Pressable>
        </View>
      </View>
      {!compact && enabled ? (
        <View style={styles.expandedBody}>
          <View style={styles.metrics}>
            <Metric label="GPU LOAD" icon="▣" value={gpu?.usage_percent == null ? '--' : `${gpu.usage_percent.toFixed(0)}%`} percent={gpu?.usage_percent ?? 0} detail={gpu?.available ? `${gpu.name}${gpu.temperature_c == null ? '' : ` · ${gpu.temperature_c.toFixed(0)}°C`}` : 'No compatible GPU detected'} />
            <Metric label="VRAM" icon="▦" value={gpu?.available ? `${gpu.memory_percent.toFixed(0)}%` : '--'} percent={gpu?.memory_percent ?? 0} detail={gpu?.available ? `${gpu.memory_used_gb.toFixed(1)} / ${gpu.memory_total_gb.toFixed(1)} GB` : 'Waiting for telemetry'} />
            <Metric label="CPU" icon="◇" value={cpu ? `${cpu.usage_percent.toFixed(0)}%` : '--'} percent={cpu?.usage_percent ?? 0} detail={cpu ? `${cpu.logical_cores} logical cores` : 'Waiting for telemetry'} />
            <Metric label="SYSTEM RAM" icon="▦" value={memory ? `${memory.usage_percent.toFixed(0)}%` : '--'} percent={memory?.usage_percent ?? 0} detail={memory ? `${memory.used_gb.toFixed(1)} / ${memory.total_gb.toFixed(1)} GB` : 'Waiting for telemetry'} />
          </View>
          <RuntimeProfiles runtime={snapshot?.tts_runtime} />
        </View>
      ) : null}
    </View>
  );
}

function RuntimeProfiles({ runtime }: { runtime?: Record<string, unknown> }) {
  const profiles = Array.isArray(runtime?.profiles) ? runtime.profiles as Array<Record<string, unknown>> : [];
  const running = profiles.filter((profile) => profile.running === true);
  const label = running.length ? `${running.length} Running` : 'Idle';
  const detail = running.length ? running.map((profile) => String(profile.loaded_model_id || profile.profile_id || 'TTS worker')).join(' · ') : 'No TTS worker running';
  return <View style={styles.runtimeProfiles}><View style={styles.runtimeHeader}><Text style={styles.runtimeTitle}>▣  TTS RUNTIME PROFILES</Text><Text style={styles.runtimeState}>{label}</Text></View><View style={styles.track}><View style={[styles.fill, { width: running.length ? '100%' : '0%', backgroundColor: '#34d399' }]} /></View><Text style={styles.detail}>{detail}</Text></View>;
}

function Metric({ label, icon, value, percent, detail }: { label: string; icon: string; value: string; percent: number; detail: string }) {
  const level = percent >= 90 ? '#f87171' : percent >= 70 ? '#f59e0b' : '#34d399';
  return <View style={styles.metric}><View style={styles.metricHeader}><Text style={styles.metricLabel}>{icon}  {label}</Text><Text style={styles.metricValue}>{value}</Text></View><View style={styles.track}><View style={[styles.fill, { width: `${Math.max(0, Math.min(100, percent))}%`, backgroundColor: level }]} /></View><Text numberOfLines={1} style={styles.detail}>{detail}</Text></View>;
}

function formatCompact(gpu: ResourceSnapshot['gpu'] | undefined, cpu: number | undefined, memory: ResourceSnapshot['memory'] | undefined) {
  return `GPU ${gpu?.usage_percent == null ? '--' : `${gpu.usage_percent.toFixed(0)}%`}   VRAM ${gpu?.available ? `${gpu.memory_percent.toFixed(0)}%` : '--'}   CPU ${cpu == null ? '--' : `${cpu.toFixed(0)}%`}   RAM ${memory ? `${memory.usage_percent.toFixed(0)}%` : '--'}`;
}

function readStoredBoolean(key: string, fallback: boolean): boolean {
  try { const value = globalThis.localStorage?.getItem(key); return value == null ? fallback : value === 'true'; } catch { return fallback; }
}
function storeBoolean(key: string, value: boolean) { try { globalThis.localStorage?.setItem(key, String(value)); } catch { /* Native storage is intentionally optional. */ } }

const styles = StyleSheet.create({
  root: { flexShrink: 0, backgroundColor: 'rgba(13,19,33,0.98)', borderTopWidth: 1, borderTopColor: 'rgba(96,165,250,0.22)', paddingHorizontal: 20, paddingVertical: 10, gap: 9 },
  header: { minHeight: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: 8 }, headerRight: { flex: 1, flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: 8 },
  power: { width: 20, height: 20, alignItems: 'center', justifyContent: 'center' }, powerOn: {}, powerText: { color: '#f8fafc', fontSize: 14 }, monitorIcon: { color: '#60a5fa', fontSize: 14 },
  title: { color: '#e2e8f0', fontSize: 13, fontWeight: '800', letterSpacing: 0.65 },
  status: { color: '#64748b', fontFamily: 'monospace', fontSize: 13 }, compactReadings: { color: '#d9e2ef', fontFamily: 'monospace', fontSize: 13 },
  collapse: { width: 22, height: 20, alignItems: 'center', justifyContent: 'center' }, collapseText: { color: '#94a3b8', fontSize: 15 },
  expandedBody: { gap: 10 }, metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 }, metric: { minWidth: 180, flex: 1, backgroundColor: 'rgba(9,13,22,.72)', borderWidth: 1, borderColor: 'rgba(148,163,184,.12)', borderRadius: 6, padding: 9, gap: 5 },
  metricHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 }, metricLabel: { color: '#94a3b8', fontSize: 13, fontWeight: '800' }, metricValue: { color: '#f8fafc', fontFamily: 'monospace', fontSize: 13, fontWeight: '800' },
  track: { height: 5, borderRadius: 3, overflow: 'hidden', backgroundColor: '#172033' }, fill: { height: '100%', borderRadius: 3 }, detail: { color: '#64748b', fontFamily: 'monospace', fontSize: 13 },
  runtimeProfiles: { backgroundColor: 'rgba(9,13,22,.72)', borderWidth: 1, borderColor: 'rgba(148,163,184,.12)', borderRadius: 6, padding: 9, gap: 5 }, runtimeHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, runtimeTitle: { color: '#93c5fd', fontSize: 13, fontWeight: '800' }, runtimeState: { color: '#f8fafc', fontFamily: 'monospace', fontSize: 13, fontWeight: '800' },
});
