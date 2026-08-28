import type { PropsWithChildren, ReactNode } from 'react';
import type { StyleProp, ViewStyle } from 'react-native';
import { StyleSheet, Text, View } from 'react-native';

export const widgetTokens = { background: '#0b0f19', border: '#1c2638', activeBorder: '#3b82f6' } as const;

export function WidgetCard({ title, subtitle, action, active = false, children, style }: PropsWithChildren<{
  title?: string; subtitle?: string; action?: ReactNode; active?: boolean; style?: StyleProp<ViewStyle>;
}>) {
  return (
    <View style={[styles.card, active && styles.active, style]}>
      {title || subtitle || action ? <View style={styles.header}><View style={styles.copy}>{title ? <Text style={styles.title}>{title}</Text> : null}{subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}</View>{action}</View> : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: widgetTokens.background, borderWidth: 1, borderColor: widgetTokens.border, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, gap: 8 },
  active: { borderColor: widgetTokens.activeBorder },
  header: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  copy: { flex: 1, gap: 3 },
  title: { color: '#f5f7fa', fontSize: 16, fontWeight: '800' },
  subtitle: { color: '#8e9db1', fontSize: 13, lineHeight: 18 },
});
