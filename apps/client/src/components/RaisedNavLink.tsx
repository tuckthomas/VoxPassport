import { Link } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text } from 'react-native';
import { raisedControlSurface } from '@/components/RaisedButton';
import { StatusLight } from '@/components/StatusLight';

export function RaisedNavLink({
  href,
  label,
  icon,
  selected,
  compact = false,
}: {
  href: string;
  label: string;
  icon: string;
  selected: boolean;
  compact?: boolean;
}) {
  const [pressed, setPressed] = useState(false);
  return <Link href={href as never} asChild>
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={label}
      accessibilityState={{ selected }}
      onPressIn={() => setPressed(true)}
      onPressOut={() => setPressed(false)}
      style={StyleSheet.flatten([styles.base, compact && styles.compact, raisedControlSurface('#2563eb', pressed, selected)])}
    >
      <StatusLight tone={selected ? 'white' : 'off'} size={7} />
      <Text style={styles.icon}>{icon}</Text>
      <Text numberOfLines={1} style={styles.label}>{label}</Text>
    </Pressable>
  </Link>;
}

const styles = StyleSheet.create({
  base: { minHeight: 42, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 8, borderRadius: 7, borderWidth: 1, marginBottom: 6 },
  compact: { minWidth: 190 },
  icon: { width: 18, textAlign: 'center', color: '#ffffff', fontSize: 14, fontWeight: '800' },
  label: { flex: 1, color: '#ffffff', fontFamily: 'Plus Jakarta Sans, system-ui, -apple-system, sans-serif', fontSize: 13, fontWeight: '800', letterSpacing: 0.4 },
});
