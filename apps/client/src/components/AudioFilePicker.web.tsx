import type { ChangeEvent } from 'react';
import { useRef, useState } from 'react';
import { Pressable, StyleSheet, Text } from 'react-native';

export function AudioFilePicker({ onSelect }: { onSelect: (uri: string, name: string) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [hovered, setHovered] = useState(false);

  function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    onSelect(URL.createObjectURL(file), file.name);
    event.target.value = '';
  }

  return <>
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Select reference audio file"
      onHoverIn={() => setHovered(true)}
      onHoverOut={() => setHovered(false)}
      onPress={() => inputRef.current?.click()}
      style={[styles.zone, hovered && styles.zoneHovered]}
    >
      <Text style={[styles.title, hovered && styles.hoveredText]}>Click to select or drag WAV, MP3, M4A</Text>
      <Text style={styles.hint}>10–15 seconds of clean speech recommended for neural cloning</Text>
    </Pressable>
    <input ref={inputRef} type="file" accept="audio/*,.wav,.mp3,.m4a" onChange={choose} style={{ display: 'none' }} />
  </>;
}

const styles = StyleSheet.create({
  zone: { minHeight: 120, alignItems: 'center', justifyContent: 'center', padding: 10, backgroundColor: '#101622', borderWidth: 1, borderStyle: 'dashed', borderColor: '#25334a', borderRadius: 4 },
  zoneHovered: { borderColor: '#3b82f6' },
  title: { color: '#f8fafc', fontSize: 14, fontWeight: '600', textAlign: 'center' },
  hoveredText: { color: '#3b82f6' },
  hint: { marginTop: 6, color: '#94a3b8', fontSize: 13, textAlign: 'center' },
});
