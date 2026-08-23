import type { PropsWithChildren, ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/theme';

export function Card({ title, subtitle, children, action }: PropsWithChildren<{ title?: string; subtitle?: string; action?: ReactNode }>) {
  return (
    <View style={styles.card}>
      {title || subtitle || action ? (
        <View style={styles.header}>
          <View style={styles.headerCopy}>
            {title ? <Text style={styles.title}>{title}</Text> : null}
            {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
          </View>
          {action}
        </View>
      ) : null}
      {children}
    </View>
  );
}

export function ActionButton({
  label,
  onPress,
  disabled = false,
  destructive = false,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  destructive?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        destructive && styles.buttonDanger,
        disabled && styles.buttonDisabled,
        pressed && !disabled && styles.buttonPressed,
      ]}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    gap: theme.spacing.md,
    padding: theme.spacing.md,
    backgroundColor: theme.colors.surface,
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
  },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: theme.spacing.md },
  headerCopy: { flex: 1, gap: 3 },
  title: { color: theme.colors.text, fontSize: 18, fontWeight: '700' },
  subtitle: { color: theme.colors.muted, fontSize: 13, lineHeight: 18 },
  button: { backgroundColor: theme.colors.accent, paddingHorizontal: 14, paddingVertical: 10, borderRadius: theme.radius.sm },
  buttonDanger: { backgroundColor: theme.colors.danger },
  buttonDisabled: { opacity: 0.45 },
  buttonPressed: { opacity: 0.8 },
  buttonText: { color: '#FFFFFF', fontWeight: '700', textAlign: 'center' },
});
