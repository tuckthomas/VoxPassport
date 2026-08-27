import { Link, usePathname } from 'expo-router';
import type { PropsWithChildren } from 'react';
import { useEffect, useState } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import type { VoiceProfile } from '@/api/contracts';
import { useVoxPassportApi } from '@/api/useVoxPassportApi';
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
  const { width } = useWindowDimensions();
  const desktop = width >= 1040;
  const target = useRuntimeTarget();
  const api = useVoxPassportApi();
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);

  useEffect(() => {
    if (!target.ready) return;
    api.voiceProfiles().then((response) => setProfiles(response.profiles)).catch(() => setProfiles([]));
  }, [api, target.ready, target.activeBaseUrl, pathname]);

  const activeVoice = profiles.find((profile) => profile.is_active);

  return (
    <View style={styles.app}>
      <View style={styles.header}>
        <Link href="/translator" asChild>
          <Pressable accessibilityLabel="Open Translator Studio" style={styles.brand}>
            <Image source={require('../../assets/VoxPassport_icon_256.png')} style={styles.logo} />
            <Text style={styles.brandTitle}>VoxPassport</Text>
          </Pressable>
        </Link>
        <View style={styles.headerActions}>
          {activeVoice ? (
            <View style={styles.activeVoiceBadge}>
              <Text style={styles.activeVoiceLabel}>ACTIVE VOICE</Text>
              <Text numberOfLines={1} style={styles.activeVoiceName}>{activeVoice.profile_name}</Text>
            </View>
          ) : null}
          <Link href="/runtime" asChild>
            <Pressable accessibilityLabel="Open runtime and audio settings" style={styles.runtimeSwitch}>
              <View style={styles.runtimeLight} />
              <Text style={styles.runtimeReady}>READY</Text>
              <View style={styles.runtimeDial}><Text style={styles.runtimeArrow}>◀</Text></View>
              <Text style={styles.runtimeDemand}>ON{desktop ? '\n' : ' '}DEMAND</Text>
              <View style={styles.runtimeLightOff} />
            </Pressable>
          </Link>
          <Link href="/runtime" asChild>
            <Pressable style={styles.headerButton}><Text style={styles.headerButtonText}>▣  RUNTIME & AUDIO</Text></Pressable>
          </Link>
        </View>
      </View>

      <View style={[styles.workspace, !desktop && styles.workspaceCompact]}>
        {desktop ? (
          <View style={styles.sidebar}>
            <View style={styles.navSection}>
              {navigation.map((item) => (
                <SidebarNav key={item.href} href={item.href} label={item.label} icon={item.icon} active={pathname === item.href} />
              ))}
            </View>
            <View style={styles.profilesHeader}>
              <Text style={styles.profilesTitle}>VOICE PROFILES</Text>
              <View style={styles.countBadge}><Text style={styles.countText}>{profiles.length} {profiles.length === 1 ? 'PROFILE' : 'PROFILES'}</Text></View>
            </View>
            <ScrollView contentContainerStyle={styles.profileList}>
              {profiles.map((profile) => (
                <Link key={profile.profile_id} href="/voice-profiles" asChild>
                  <Pressable style={StyleSheet.flatten([styles.profileCard, profile.is_active && styles.profileCardActive])}>
                    <View style={styles.profileTitleRow}>
                      <View style={[styles.profileLed, profile.is_active && styles.profileLedActive]} />
                      <Text numberOfLines={1} style={styles.profileName}>{profile.profile_name}</Text>
                      <Text style={styles.profileMenu}>•••</Text>
                    </View>
                    <Text style={styles.profileMeta}>{(profile.ref_lang || 'unknown').toUpperCase()} REFERENCE</Text>
                    <View style={styles.profileActions}>
                      <View style={styles.miniButton}><Text style={styles.miniButtonText}>▶ ORIGINAL</Text></View>
                      <View style={[styles.miniButton, styles.miniButtonBlue]}><Text style={styles.miniButtonText}>▶ CLONE</Text></View>
                    </View>
                  </Pressable>
                </Link>
              ))}
              {!profiles.length ? (
                <View style={styles.emptyProfiles}>
                  <Text style={styles.emptyProfilesText}>No enrolled voice profiles reported by this runtime.</Text>
                </View>
              ) : null}
            </ScrollView>
            <View style={styles.sidebarFooter}>
              <View style={styles.onlineDot} />
              <Text style={styles.sidebarFooterText}>{target.mode.toUpperCase()} · {target.activeBaseUrl.replace(/^https?:\/\//, '')}</Text>
            </View>
          </View>
        ) : (
          <ScrollView horizontal contentContainerStyle={styles.mobileNav} showsHorizontalScrollIndicator={false}>
            {navigation.map((item) => (
              <SidebarNav key={item.href} href={item.href} label={item.label} icon={item.icon} active={pathname === item.href} compact />
            ))}
          </ScrollView>
        )}
        <View style={styles.main}>{children}</View>
      </View>
    </View>
  );
}

function SidebarNav({ href, label, icon, active, compact = false }: { href: string; label: string; icon: string; active: boolean; compact?: boolean }) {
  return (
    <Link href={href as never} asChild>
      <Pressable accessibilityRole="link" style={StyleSheet.flatten([styles.navButton, compact && styles.navButtonCompact, active && styles.navButtonActive])}>
        <View style={[styles.navLed, active && styles.navLedActive]} />
        <Text style={styles.navIcon}>{icon}</Text>
        <Text numberOfLines={1} style={styles.navText}>{label}</Text>
      </Pressable>
    </Link>
  );
}

const font = 'Plus Jakarta Sans, system-ui, -apple-system, sans-serif';

const styles = StyleSheet.create({
  app: { flex: 1, minHeight: '100%', backgroundColor: palette.base },
  header: { height: 56, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 24, backgroundColor: palette.surface, borderBottomWidth: 1, borderBottomColor: palette.border },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  logo: { width: 30, height: 30, resizeMode: 'contain' },
  brandTitle: { color: palette.heading, fontFamily: font, fontSize: 15, fontWeight: '800', letterSpacing: -0.3 },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  activeVoiceBadge: { maxWidth: 230, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 5, borderRadius: 20, backgroundColor: 'rgba(59,130,246,0.1)', borderWidth: 1, borderColor: 'rgba(59,130,246,0.3)' },
  activeVoiceLabel: { color: palette.muted, fontFamily: font, fontSize: 9, fontWeight: '700' },
  activeVoiceName: { flexShrink: 1, color: '#60a5fa', fontFamily: font, fontSize: 11, fontWeight: '800' },
  runtimeSwitch: { height: 40, minWidth: 184, paddingHorizontal: 7, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderRadius: 3, borderWidth: 1, borderColor: '#252a31', backgroundColor: '#15181d', boxShadow: 'inset 0 1px 4px rgba(0,0,0,.8), 0 3px 0 #020617' },
  runtimeLight: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#34d399', boxShadow: '0 0 8px #34d399' },
  runtimeLightOff: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#26303a' },
  runtimeReady: { width: 48, textAlign: 'center', color: palette.heading, fontFamily: font, fontSize: 8, fontWeight: '800', letterSpacing: 0.7 },
  runtimeDemand: { width: 52, textAlign: 'center', color: '#6b7280', fontFamily: font, fontSize: 8, lineHeight: 9, fontWeight: '800', letterSpacing: 0.7 },
  runtimeDial: { width: 29, height: 29, borderRadius: 15, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: '#636b75', backgroundColor: '#7b838c', boxShadow: '0 2px 3px rgba(0,0,0,.9), inset 0 1px 2px rgba(255,255,255,.8)' },
  runtimeArrow: { color: '#080b10', fontSize: 10, fontWeight: '800' },
  headerButton: { paddingHorizontal: 16, paddingVertical: 8, borderRadius: 4, backgroundColor: palette.accentDark, borderWidth: 1, borderColor: palette.accent, boxShadow: '0 3px 0 #1d4ed8' },
  headerButtonText: { color: '#ffffff', fontFamily: font, fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
  workspace: { flex: 1, minHeight: 0, flexDirection: 'row' },
  workspaceCompact: { flexDirection: 'column' },
  sidebar: { width: 360, flexShrink: 0, backgroundColor: palette.surface, borderRightWidth: 1, borderRightColor: palette.border },
  navSection: { gap: 8, paddingHorizontal: 20, paddingVertical: 16, borderBottomWidth: 1, borderBottomColor: palette.border },
  navButton: { minHeight: 42, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 8, borderRadius: 4, backgroundColor: palette.accentDark, borderWidth: 1, borderColor: palette.accent, boxShadow: '0 3px 0 #1d4ed8, 0 5px 10px rgba(0,0,0,.35)' },
  navButtonActive: { transform: [{ translateY: 3 }], boxShadow: 'inset 0 2px 4px rgba(0,0,0,.5)' },
  navButtonCompact: { minWidth: 190 },
  navLed: { width: 7, height: 7, borderRadius: 4, backgroundColor: 'rgba(255,255,255,.25)', borderWidth: 1, borderColor: 'rgba(255,255,255,.35)' },
  navLedActive: { backgroundColor: '#ffffff', borderColor: '#ffffff', boxShadow: '0 0 7px 2px rgba(255,255,255,.9)' },
  navIcon: { width: 18, textAlign: 'center', color: '#ffffff', fontSize: 14, fontWeight: '800' },
  navText: { flex: 1, color: '#ffffff', fontFamily: font, fontSize: 12, fontWeight: '800', letterSpacing: 0.4 },
  profilesHeader: { height: 53, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: palette.border },
  profilesTitle: { color: palette.muted, fontFamily: font, fontSize: 11, fontWeight: '800', letterSpacing: 0.7 },
  countBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12, backgroundColor: 'rgba(59,130,246,.1)', borderWidth: 1, borderColor: 'rgba(59,130,246,.3)' },
  countText: { color: '#60a5fa', fontFamily: font, fontSize: 9, fontWeight: '700' },
  profileList: { flexGrow: 1, gap: 10, padding: 16 },
  profileCard: { padding: 14, gap: 10, borderRadius: 10, backgroundColor: palette.input, borderWidth: 1, borderColor: palette.border },
  profileCardActive: { borderColor: palette.accent },
  profileTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  profileLed: { width: 8, height: 8, borderRadius: 4, backgroundColor: palette.dim },
  profileLedActive: { backgroundColor: palette.success, boxShadow: '0 0 7px rgba(16,185,129,.85)' },
  profileName: { flex: 1, color: palette.heading, fontFamily: font, fontSize: 13, fontWeight: '700' },
  profileMenu: { color: palette.dim, fontSize: 12, letterSpacing: 1 },
  profileMeta: { color: palette.dim, fontFamily: 'JetBrains Mono, monospace', fontSize: 10, fontWeight: '500' },
  profileActions: { flexDirection: 'row', gap: 7 },
  miniButton: { flex: 1, paddingVertical: 6, alignItems: 'center', borderRadius: 4, backgroundColor: '#172030', borderWidth: 1, borderColor: palette.borderStrong },
  miniButtonBlue: { backgroundColor: 'rgba(59,130,246,.12)', borderColor: 'rgba(59,130,246,.35)' },
  miniButtonText: { color: palette.body, fontFamily: font, fontSize: 9, fontWeight: '800' },
  emptyProfiles: { padding: 16, borderRadius: 10, borderWidth: 1, borderStyle: 'dashed', borderColor: palette.borderStrong },
  emptyProfilesText: { color: palette.dim, fontFamily: font, fontSize: 12, lineHeight: 18, textAlign: 'center' },
  sidebarFooter: { minHeight: 42, paddingHorizontal: 18, flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, borderTopColor: palette.border },
  onlineDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: palette.success },
  sidebarFooterText: { flex: 1, color: palette.dim, fontFamily: 'JetBrains Mono, monospace', fontSize: 9 },
  mobileNav: { gap: 8, padding: 10, backgroundColor: palette.surface, borderBottomWidth: 1, borderBottomColor: palette.border },
  main: { flex: 1, minWidth: 0, minHeight: 0, backgroundColor: palette.base },
});
