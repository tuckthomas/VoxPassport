import { Link, usePathname, useRouter } from 'expo-router';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import type { PropsWithChildren } from 'react';
import { useEffect, useState } from 'react';
import { Alert, Image, Modal, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import type { VoiceProfile } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
import { RaisedButton } from '@/components/RaisedButton';
import { IconButton } from '@/components/IconButton';
import { TrashIcon } from '@/components/icons/TrashIcon';
import { ResourceMonitor } from '@/components/ResourceMonitor';
import { RaisedNavLink } from '@/components/RaisedNavLink';
import { StatusLight } from '@/components/StatusLight';
import { WidgetCard } from '@/components/WidgetCard';
import { useRuntimeTarget } from '@/config/RuntimeTargetContext';

const palette = {
  base: '#090d16', surface: '#101622', input: '#0b0f19', border: '#1c2638', borderStrong: '#25334a',
  heading: '#f8fafc', body: '#cbd5e1', muted: '#94a3b8', dim: '#64748b', accent: '#3b82f6',
  accentDark: '#2563eb', sky: '#0284c7', success: '#10b981', danger: '#ef4444',
};

const navigation = [
  { href: '/translator', label: 'Translator Studio', icon: '文' },
  { href: '/voice-profiles', label: 'Create Voice Profile', icon: '◉' },
  { href: '/models', label: 'Model Settings', icon: '✣' },
] as const;

export function StudioShell({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const desktop = width >= 1040;
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const player = useAudioPlayer(null);
  const playerStatus = useAudioPlayerStatus(player);
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [playingProfileId, setPlayingProfileId] = useState<string | null>(null);
  const [overlayOpen, setOverlayOpen] = useState(false);

  useEffect(() => {
    if (!target.ready) return;
    api.voiceProfiles().then((response) => setProfiles(response.profiles)).catch(() => setProfiles([]));
  }, [api, target.ready, target.activeBaseUrl, pathname]);

  useEffect(() => {
    if (playerStatus.didJustFinish || playerStatus.error) setPlayingProfileId(null);
  }, [playerStatus.didJustFinish, playerStatus.error]);

  function playProfile(playbackId: string, path: string) {
    if (playingProfileId === playbackId) {
      player.pause();
      void player.seekTo(0);
      setPlayingProfileId(null);
      return;
    }
    setPlayingProfileId(playbackId);
    player.replace(api.mediaUrl(path));
    player.play();
  }

  async function toggleProfile(profile: VoiceProfile) {
    await api.activateVoiceProfile(profile.is_active ? '' : profile.profile_id);
    const response = await api.voiceProfiles();
    setProfiles(response.profiles);
  }

  function deleteProfile(profile: VoiceProfile) {
    Alert.alert('Delete voice profile?', `Delete ${profile.profile_name} and its saved audio?`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => void api.deleteVoiceProfile(profile.profile_id).then(() => api.voiceProfiles()).then((response) => setProfiles(response.profiles)) },
    ]);
  }

  return (
    <View style={styles.app}>
      <View style={styles.header}>
        <Link href="/translator" asChild>
          <Pressable accessibilityLabel="Open Translator Studio" style={styles.brand}>
            <Image source={require('../../assets/VoxPassport_icon_256.png')} resizeMode="contain" style={styles.logo} />
            <Text style={styles.brandTitle}>VoxPassport</Text>
          </Pressable>
        </Link>
        <View style={styles.headerActions}>
          <Link href="/runtime" asChild>
            <Pressable accessibilityLabel="Open runtime and audio settings" style={styles.runtimeSwitch}>
              <StatusLight tone="green" size={7} />
              <Text style={styles.runtimeReady}>READY</Text>
              <View style={styles.runtimeDial}><Text style={styles.runtimeArrow}>◀</Text></View>
              <Text style={styles.runtimeDemand}>ON{desktop ? '\n' : ' '}DEMAND</Text>
              <StatusLight tone="off" size={7} />
            </Pressable>
          </Link>
          <RaisedButton label="▣  MEETING OVERLAY" compact backgroundColor="#2563eb" onPress={() => setOverlayOpen(true)} />
        </View>
      </View>

      <View style={[styles.workspace, !desktop && styles.workspaceCompact]}>
        {desktop ? (
          <View style={styles.sidebar}>
            <View style={styles.navSection}>
              {navigation.map((item) => (
                <RaisedNavLink key={item.href} href={item.href} label={item.label} icon={item.icon} selected={pathname === item.href} />
              ))}
            </View>
            <View style={styles.profilesHeader}>
              <Text style={styles.profilesTitle}>VOICE PROFILES</Text>
              <View style={styles.countBadge}><Text style={styles.countText}>{profiles.length} {profiles.length === 1 ? 'PROFILE' : 'PROFILES'}</Text></View>
            </View>
            <ScrollView contentContainerStyle={styles.profileList}>
              {profiles.map((profile) => (
                <WidgetCard key={profile.profile_id} active={Boolean(profile.is_active)} style={styles.profileCard}>
                    <View style={styles.profileTitleRow}>
                      <Pressable accessibilityRole="switch" accessibilityState={{ checked: Boolean(profile.is_active) }} accessibilityLabel={profile.is_active ? `Deactivate ${profile.profile_name}` : `Activate ${profile.profile_name}`} onPress={() => void toggleProfile(profile)} style={styles.profileLedButton}><StatusLight tone={profile.is_active ? 'green' : 'red'} size={9} /></Pressable>
                      <Text numberOfLines={1} style={styles.profileName}>{profile.profile_name}</Text>
                      <IconButton label={`Delete ${profile.profile_name}`} tone="danger" onPress={() => deleteProfile(profile)}><TrashIcon size={14} /></IconButton>
                    </View>
                    <View style={styles.profileDetails}><Text style={styles.profileTag}>◎ {languageName(profile.ref_lang)}</Text><Text style={styles.profileMeta}>{profile.pitch_hz ? `${profile.pitch_hz}Hz` : '130Hz Pitch'}</Text></View>
                    <View style={styles.profileActions}>
                      <View style={styles.profileAction}><RaisedButton label="▶ ORIGINAL" compact compactLabelSize={9} latched={playingProfileId === profile.profile_id} style={styles.profileActionButton} backgroundColor="#059669" disabled={!profile.has_audio} onPress={() => playProfile(profile.profile_id, `/api/voice/audio/${encodeURIComponent(profile.profile_id)}?t=${Date.now()}`)} /></View>
                      <View style={styles.profileAction}><RaisedButton label="▶ TRANSLATION" compact compactLabelSize={9} latched={playingProfileId === `translation:${profile.profile_id}`} style={styles.profileActionButton} backgroundColor="#059669" disabled={!profile.has_translation_audio} onPress={() => playProfile(`translation:${profile.profile_id}`, `/api/voice/translation/${encodeURIComponent(profile.profile_id)}?t=${Date.now()}`)} /></View>
                      <View style={styles.profileAction}><RaisedButton label="✎ EDIT" compact compactLabelSize={9} style={styles.profileActionButton} backgroundColor="#1d4f91" onPress={() => router.push({ pathname: '/voice-profiles', params: { profile: profile.profile_id } } as never)} /></View>
                    </View>
                </WidgetCard>
              ))}
              {!profiles.length ? (
                <View style={styles.emptyProfiles}>
                  <Text style={styles.emptyProfilesText}>No enrolled voice profiles reported by this runtime.</Text>
                </View>
              ) : null}
            </ScrollView>
            <View style={styles.sidebarFooter}>
              <StatusLight tone="green" size={7} />
              <Text style={styles.sidebarFooterText}>{target.mode.toUpperCase()} · {target.activeBaseUrl.replace(/^https?:\/\//, '')}</Text>
            </View>
          </View>
        ) : (
          <ScrollView horizontal contentContainerStyle={styles.mobileNav} showsHorizontalScrollIndicator={false}>
            {navigation.map((item) => (
              <RaisedNavLink key={item.href} href={item.href} label={item.label} icon={item.icon} selected={pathname === item.href} compact />
            ))}
          </ScrollView>
        )}
        <View style={styles.contentColumn}>
          <View style={styles.main}>{children}</View>
          <ResourceMonitor />
        </View>
      </View>
      <Modal visible={overlayOpen} transparent animationType="fade" onRequestClose={() => setOverlayOpen(false)}>
        <View style={styles.overlayBackdrop}>
          <WidgetCard title="Meeting Overlay" subtitle="Floating subtitles for Zoom, Google Meet, Teams, and other conferencing apps." style={styles.overlayCard}>
            <View style={styles.overlayPreview}><Text style={styles.overlayPreviewText}>TRANSLATED SUBTITLES WILL APPEAR HERE</Text></View>
            <Text style={styles.overlayBody}>The overlay launcher is restored to its original place. Conference-window attachment is intentionally not wired yet.</Text>
            <View style={styles.overlayActions}><RaisedButton label="Close" backgroundColor="#475569" onPress={() => setOverlayOpen(false)} /></View>
          </WidgetCard>
        </View>
      </Modal>
    </View>
  );
}

function languageName(code?: string) {
  const names: Record<string, string> = { en: 'English (US)', ro: 'Romanian (RO)', es: 'Spanish (ES)', fr: 'French (FR)', de: 'German (DE)', it: 'Italian (IT)' };
  return names[(code || 'en').toLowerCase()] || (code || 'Unknown').toUpperCase();
}

const font = 'Plus Jakarta Sans, system-ui, -apple-system, sans-serif';

const styles = StyleSheet.create({
  app: { flex: 1, minHeight: '100%', backgroundColor: palette.base },
  header: { height: 56, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 24, backgroundColor: palette.surface, borderBottomWidth: 1, borderBottomColor: palette.border },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  logo: { width: 30, height: 30 },
  brandTitle: { color: palette.heading, fontFamily: font, fontSize: 15, fontWeight: '800', letterSpacing: -0.3 },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  runtimeSwitch: { height: 40, minWidth: 184, paddingHorizontal: 7, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderRadius: 3, borderWidth: 1, borderColor: '#252a31', backgroundColor: '#15181d', boxShadow: 'inset 0 1px 4px rgba(0,0,0,.8), 0 3px 0 #020617' },
  runtimeReady: { width: 58, textAlign: 'center', color: palette.heading, fontFamily: font, fontSize: 13, fontWeight: '800', letterSpacing: 0.7 },
  runtimeDemand: { width: 72, textAlign: 'center', color: '#6b7280', fontFamily: font, fontSize: 13, lineHeight: 16, fontWeight: '800', letterSpacing: 0.7 },
  runtimeDial: { width: 29, height: 29, borderRadius: 15, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: '#636b75', backgroundColor: '#7b838c', boxShadow: '0 2px 3px rgba(0,0,0,.9), inset 0 1px 2px rgba(255,255,255,.8)' },
  runtimeArrow: { color: '#080b10', fontSize: 13, fontWeight: '800' },
  workspace: { flex: 1, minHeight: 0, flexDirection: 'row' },
  workspaceCompact: { flexDirection: 'column' },
  sidebar: { width: 360, flexShrink: 0, backgroundColor: palette.surface, borderRightWidth: 1, borderRightColor: palette.border },
  navSection: { gap: 8, paddingHorizontal: 20, paddingVertical: 16, borderBottomWidth: 1, borderBottomColor: palette.border },
  profilesHeader: { height: 53, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: palette.border },
  profilesTitle: { color: palette.muted, fontFamily: font, fontSize: 13, fontWeight: '800', letterSpacing: 0.7 },
  countBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12, backgroundColor: 'rgba(59,130,246,.1)', borderWidth: 1, borderColor: 'rgba(59,130,246,.3)' },
  countText: { color: '#60a5fa', fontFamily: font, fontSize: 13, fontWeight: '700' },
  profileList: { flexGrow: 1, gap: 10, padding: 16 },
  profileCard: { padding: 14, gap: 10 },
  profileTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  profileLedButton: { width: 20, height: 20, alignItems: 'center', justifyContent: 'center' },
  profileName: { flex: 1, color: palette.heading, fontFamily: font, fontSize: 13, fontWeight: '700' },
  profileMenu: { color: palette.dim, fontSize: 13, letterSpacing: 1 },
  profileDetails: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 6 },
  profileTag: { color: '#7db7ff', backgroundColor: '#12233a', borderWidth: 1, borderColor: '#23466f', borderRadius: 4, paddingHorizontal: 7, paddingVertical: 3, fontFamily: 'JetBrains Mono, monospace', fontSize: 13, fontWeight: '700' },
  profileMeta: { color: palette.dim, fontFamily: 'JetBrains Mono, monospace', fontSize: 13, fontWeight: '500' },
  profileActions: { flexDirection: 'row', gap: 6 },
  profileAction: { flex: 1 },
  profileActionButton: { paddingHorizontal: 4 },
  emptyProfiles: { padding: 16, borderRadius: 10, borderWidth: 1, borderStyle: 'dashed', borderColor: palette.borderStrong },
  emptyProfilesText: { color: palette.dim, fontFamily: font, fontSize: 13, lineHeight: 18, textAlign: 'center' },
  sidebarFooter: { minHeight: 42, paddingHorizontal: 18, flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, borderTopColor: palette.border },
  sidebarFooterText: { flex: 1, color: palette.dim, fontFamily: 'JetBrains Mono, monospace', fontSize: 13 },
  mobileNav: { gap: 8, padding: 10, backgroundColor: palette.surface, borderBottomWidth: 1, borderBottomColor: palette.border },
  contentColumn: { flex: 1, minWidth: 0, minHeight: 0 },
  main: { flex: 1, minWidth: 0, minHeight: 0, backgroundColor: palette.base },
  overlayBackdrop: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: 'rgba(3,7,14,.86)' },
  overlayCard: { width: '100%', maxWidth: 620, padding: 20 },
  overlayPreview: { minHeight: 150, borderRadius: 10, borderWidth: 1, borderColor: '#30578b', backgroundColor: '#070b12', alignItems: 'center', justifyContent: 'center', padding: 24 },
  overlayPreviewText: { color: '#8fc4ff', fontSize: 15, fontWeight: '800', letterSpacing: 0.7, textAlign: 'center' },
  overlayBody: { color: palette.muted, fontSize: 13, lineHeight: 20 },
  overlayActions: { alignItems: 'flex-end' },
});
