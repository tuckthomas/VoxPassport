import type { ReactNode } from 'react';
import type { StyleProp, ViewStyle } from 'react-native';
import { Pressable, StyleSheet } from 'react-native';

export function IconButton({ label, children, onPress, style }: { label: string; children: ReactNode; onPress: () => void; tone?: 'neutral' | 'danger'; style?: StyleProp<ViewStyle> }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} style={({ pressed }) => [styles.base, pressed && styles.pressed, StyleSheet.flatten(style)]}>{children}</Pressable>;
}

const styles = StyleSheet.create({
  base: { width: 18, height: 18, padding: 0, borderWidth: 0, backgroundColor: 'transparent', alignItems: 'center', justifyContent: 'center' },
  pressed: { opacity: 0.7, transform: [{ scale: 0.92 }] },
});
