import type { PropsWithChildren, ReactNode } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { theme } from '@/theme';

export function Screen({
  title,
  subtitle,
  children,
  action,
}: PropsWithChildren<{ title: string; subtitle?: string; action?: ReactNode }>) {
  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.headerRow}>
          <View style={styles.headerCopy}>
            <Text style={styles.title}>{title}</Text>
            {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
          </View>
          {action}
        </View>
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.colors.background },
  content: { width: '100%', maxWidth: 1080, alignSelf: 'center', padding: theme.spacing.lg, gap: theme.spacing.md },
  headerRow: { flexDirection: 'row', gap: theme.spacing.md, alignItems: 'flex-start', justifyContent: 'space-between' },
  headerCopy: { flex: 1, gap: theme.spacing.xs },
  title: { color: theme.colors.text, fontSize: 30, fontWeight: '700' },
  subtitle: { color: theme.colors.muted, fontSize: 15, lineHeight: 21 },
});
