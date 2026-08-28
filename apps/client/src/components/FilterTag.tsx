import { Pressable, StyleSheet, Text } from 'react-native';

export function FilterTag({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: selected }} onPress={onPress} style={({ pressed }) => [styles.tag, selected && styles.selected, pressed && styles.pressed]}><Text style={[styles.label, selected && styles.selectedLabel]}>{label}</Text></Pressable>;
}

const styles = StyleSheet.create({
  tag: { minHeight: 28, paddingHorizontal: 13, paddingVertical: 5, justifyContent: 'center', borderRadius: 14, backgroundColor: '#172030', borderWidth: 1, borderColor: '#25334a' },
  selected: { backgroundColor: '#142846', borderColor: '#3b82f6' }, pressed: { opacity: 0.78 },
  label: { color: '#718096', fontSize: 13, fontWeight: '700' }, selectedLabel: { color: '#93c5fd' },
});
