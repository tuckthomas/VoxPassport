import type { ReactNode } from 'react';
import type { StyleProp, TextStyle, ViewStyle } from 'react-native';
import { Pressable, StyleSheet, Text, View } from 'react-native';

type RaisedButtonProps = {
  label: string;
  onPress?: () => void;
  disabled?: boolean;
  backgroundColor?: string;
  foregroundColor?: string;
  compact?: boolean;
  compactLabelSize?: number;
  latched?: boolean;
  icon?: ReactNode;
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
  labelStyle?: StyleProp<TextStyle>;
};

export function RaisedButton({ label, onPress, disabled = false, backgroundColor = '#2563eb', foregroundColor = '#ffffff', compact = false, compactLabelSize = 11, latched = false, icon, accessibilityLabel, style, labelStyle }: RaisedButtonProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel || label}
      accessibilityState={{ disabled, selected: latched }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.base, compact && styles.compact, raisedControlSurface(backgroundColor, pressed, latched, compact), style, disabled && styles.disabled]}
    >
      {icon ? <View style={styles.icon}>{icon}</View> : null}
      <Text numberOfLines={1} style={[styles.label, compact && { fontSize: compactLabelSize }, { color: foregroundColor }, labelStyle]}>{label}</Text>
    </Pressable>
  );
}

export function raisedControlSurface(backgroundColor: string, pressed: boolean, latched = false, compact = false): ViewStyle {
  const depth = darken(backgroundColor, 0.42);
  const ambient = withAlpha(depth, 0.34);
  const depressed = pressed || latched;
  const raisedDepth = compact ? 3 : 6;
  const ambientDepth = compact ? 4 : 12;
  return {
    backgroundColor,
    borderColor: lighten(backgroundColor, 0.18),
    boxShadow: depressed ? `0 1px 0 ${depth}, 0 3px 6px ${ambient}` : `0 ${raisedDepth}px 0 ${depth}, 0 ${ambientDepth}px ${compact ? 8 : 18}px ${ambient}`,
    transform: [{ translateY: depressed ? 3 : 0 }],
  };
}

function parseHex(value: string): [number, number, number] | null {
  const normalized = value.trim().replace(/^#/, '');
  if (!/^[0-9a-f]{6}$/i.test(normalized)) return null;
  return [Number.parseInt(normalized.slice(0, 2), 16), Number.parseInt(normalized.slice(2, 4), 16), Number.parseInt(normalized.slice(4, 6), 16)];
}

function darken(value: string, amount: number): string {
  const rgb = parseHex(value);
  return rgb ? `rgb(${rgb.map((channel) => Math.round(channel * (1 - amount))).join(', ')})` : '#0f172a';
}

function lighten(value: string, amount: number): string {
  const rgb = parseHex(value);
  return rgb ? `rgb(${rgb.map((channel) => Math.round(channel + (255 - channel) * amount)).join(', ')})` : value;
}

function withAlpha(value: string, alpha: number): string {
  const channels = value.match(/\d+/g);
  return channels?.length === 3 ? `rgba(${channels.join(', ')}, ${alpha})` : 'rgba(15, 23, 42, 0.28)';
}

const styles = StyleSheet.create({
  base: { minHeight: 38, paddingHorizontal: 16, paddingVertical: 9, borderRadius: 7, borderWidth: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7, marginBottom: 6 },
  compact: { minHeight: 30, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 4, marginBottom: 3 },
  disabled: { opacity: 0.48 },
  icon: { alignItems: 'center', justifyContent: 'center' },
  label: { fontSize: 13, fontWeight: '800', letterSpacing: 0.1, textAlign: 'center' },
});
